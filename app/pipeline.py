import re
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from pymongo.database import Database

from app.analysis.extractor import analyze_email_with_validation
from app.analysis.schemas import EmailAnalysis
from app.calendar.actions import build_calendar_action
from app.calendar.detector import detect_meeting
from app.config.settings import Settings
from app.context.engine import build_next_context
from app.context.models import ThreadContext
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ProcessingRunRepository,
    ReplyDraftRepository,
    ThreadRepository,
)
from app.email.models import Email, parse_email
from app.email.normalizer import normalize_email, normalize_subject
from app.email.threading import ThreadCandidate, resolve_thread_id
from app.entities.dates import resolve_date_phrase
from app.entities.extraction import envelope_people
from app.entities.resolution import (
    derive_follow_up,
    resolve_commitment,
    resolve_meeting,
    resolve_person,
    resolve_personal_item,
    resolve_project,
)
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.email_provider import EmailProvider
from app.interfaces.llm_provider import LLMProvider
from app.knowledge.deduplication import process_new_fact
from app.knowledge.models import KnowledgeItem
from app.processing.models import EmailResult, PipelineRunSummary, ProcessingStage
from app.replies.drafter import draft_reply, needs_reply
from app.replies.models import ReplyDraft

_GMAIL_INTERNAL_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")

_FACT_FIELD_PREDICATES = {
    "requirements": "requires",
    "pain_points": "has_pain_point",
    "competitors": "mentioned_competitor",
    "objections": "raised_objection",
    "buying_signals": "showed_buying_signal",
}


def _load_thread_candidates(thread_repo: ThreadRepository) -> list[ThreadCandidate]:
    candidates = []
    for doc in thread_repo.find_many({}):
        candidates.append(
            ThreadCandidate(
                thread_id=doc["thread_id"],
                normalized_subject=doc["normalized_subject"],
                participant_emails=set(doc["participant_emails"]),
                message_ids=set(doc["message_ids"]),
                last_message_at=datetime.fromisoformat(doc["last_message_at"]),
            )
        )
    return candidates


def _upsert_thread(thread_repo: ThreadRepository, thread_id: str, email: Email) -> None:
    existing = thread_repo.find_one({"thread_id": thread_id})
    participant_emails = set(existing["participant_emails"]) if existing else set()
    message_ids = set(existing["message_ids"]) if existing else set()

    participant_emails |= {email.from_.email, *(a.email for a in email.to), *(a.email for a in email.cc)}
    message_ids.add(email.message_id)

    last_message_at = email.timestamp
    if existing:
        existing_last = datetime.fromisoformat(existing["last_message_at"])
        last_message_at = max(last_message_at, existing_last)

    thread_repo.upsert_by_key(
        {"thread_id": thread_id},
        {
            "thread_id": thread_id,
            "normalized_subject": existing["normalized_subject"] if existing else normalize_subject(email.subject),
            "participant_emails": sorted(participant_emails),
            "message_ids": sorted(message_ids),
            "last_message_at": last_message_at.isoformat(),
        },
    )


def _process_knowledge(
    knowledge_repo: KnowledgeRepository,
    thread_id: str,
    analysis: EmailAnalysis,
    llm: LLMProvider,
    subject_name: str,
    source_email_id: str,
    now: datetime,
) -> None:
    stored_docs = knowledge_repo.all_for_thread(thread_id)
    items = [KnowledgeItem.model_validate(doc) for doc in stored_docs]

    for fact in analysis.facts:
        items, item = process_new_fact(
            items, thread_id, fact.subject, fact.predicate, fact.object, source_email_id, "stated", llm, now
        )
        knowledge_repo.upsert_by_key(
            {
                "thread_id": item.thread_id,
                "subject_key": item.subject_key,
                "predicate": item.predicate,
                "fact_key": item.fact_key,
            },
            item.model_dump(mode="json"),
        )

    for field, predicate in _FACT_FIELD_PREDICATES.items():
        for value in getattr(analysis, field):
            items, item = process_new_fact(
                items, thread_id, subject_name, predicate, value, source_email_id, "stated", llm, now
            )
            knowledge_repo.upsert_by_key(
                {
                    "thread_id": item.thread_id,
                    "subject_key": item.subject_key,
                    "predicate": item.predicate,
                    "fact_key": item.fact_key,
                },
                item.model_dump(mode="json"),
            )


def _process_entities(
    db,
    thread_id: str,
    email: Email,
    analysis: EmailAnalysis,
    reference_now: datetime,
) -> dict[str, list[str]]:
    # reference_now is the email's OWN timestamp, not wall-clock "now" -- this matches the
    # existing detect_meeting's established pattern (app/calendar/detector.py, called with
    # email.timestamp) so a re-run days later resolves the same relative phrase the same way.
    entities_referenced: dict[str, list[str]] = {
        "people": [], "projects": [], "commitments": [],
        "follow_ups": [], "meetings": [], "personal": [],
    }

    envelope = {addr.email.lower(): addr for addr in envelope_people(email)}
    sender_email = email.from_.email.lower()

    for mention in analysis.people_mentioned:
        mention_email = (mention.email or "").lower() or None
        is_sender = None
        if mention_email and mention_email == sender_email:
            is_sender = True
        elif mention_email and mention_email in envelope:
            is_sender = False
        person_id = resolve_person(
            db,
            {"name": mention.name, "email": mention.email, "org": mention.org},
            is_sender=is_sender,
            now=reference_now,
        )
        entities_referenced["people"].append(person_id)

    project_id_by_name: dict[str, str] = {}
    for mention in analysis.projects_mentioned:
        project_id = resolve_project(
            db, {"name": mention.name, "org": mention.org}, goal_pillar=analysis.goal_pillar
        )
        entities_referenced["projects"].append(project_id)
        project_id_by_name[mention.name] = project_id

    # FollowUps are derived ONLY from a resolved Commitment (spec S5.1.1 correction) --
    # a Meeting or PersonalItem NEVER triggers a FollowUp by itself, no matter how
    # "actionable" the meeting is. Do not add a fallback branch here.
    for raw_commitment in analysis.commitments_mentioned:
        resolved_date, date_type = resolve_date_phrase(raw_commitment.date_phrase, reference_now)
        commitment_id = resolve_commitment(
            db,
            thread_id=thread_id,
            raw=raw_commitment.model_dump(mode="json", by_alias=True),
            message_id=email.message_id,
            made_on=reference_now,
            resolved_date=resolved_date,
            date_type=date_type,
            goal_pillar=analysis.goal_pillar,
            project_id=None,
        )
        entities_referenced["commitments"].append(commitment_id)
        follow_up_id = derive_follow_up(db, commitment_id=commitment_id, thread_id=None)
        entities_referenced["follow_ups"].append(follow_up_id)

    for raw_meeting in analysis.meetings_mentioned:
        resolved_date, _ = resolve_date_phrase(raw_meeting.date_phrase, reference_now)
        # The actionable signal (spec S4.6): true for any future-oriented meeting mention,
        # even a vague one with no precise resolved_date -- false only when the LLM (or,
        # for MockLLMProvider, the simple absence of a "meet" match on past-tense "met")
        # flagged it as historical.
        actionable = not raw_meeting.is_past
        meeting_id = resolve_meeting(
            db,
            thread_id=thread_id,
            date=resolved_date,
            raw=raw_meeting.model_dump(mode="json"),
            actionable=actionable,
        )
        entities_referenced["meetings"].append(meeting_id)

    for raw_item in analysis.personal_items_mentioned:
        resolved_date, _ = resolve_date_phrase(raw_item.date_phrase, reference_now)
        item_id = resolve_personal_item(
            db, sender_email=sender_email, raw=raw_item.model_dump(mode="json"), resolved_date=resolved_date
        )
        entities_referenced["personal"].append(item_id)

    return entities_referenced


def run_pipeline(
    db: Database,
    email_provider: EmailProvider,
    llm_provider: LLMProvider,
    calendar_provider: CalendarProvider,
    settings: Settings,
) -> PipelineRunSummary:
    email_repo = EmailRepository(db)
    thread_repo = ThreadRepository(db)
    context_repo = ContextSnapshotRepository(db)
    knowledge_repo = KnowledgeRepository(db)
    reply_repo = ReplyDraftRepository(db)
    calendar_repo = CalendarActionRepository(db)
    run_repo = ProcessingRunRepository(db)

    run_id = f"run_{uuid.uuid4().hex}"
    started_at = datetime.now(timezone.utc)
    results: list[EmailResult] = []

    raw_emails = email_provider.fetch_emails(limit=settings.email_limit)

    for raw in raw_emails:
        message_id = raw.get("message_id") if isinstance(raw, dict) else None
        try:
            email = parse_email(raw)
        except ValidationError as exc:
            results.append(EmailResult(message_id=message_id, final_stage="FAILED", error=str(exc)))
            if message_id:
                email_repo.set_stage(
                    message_id,
                    ProcessingStage.FAILED.value,
                    error=str(exc),
                    failed_stage=ProcessingStage.VALIDATED.value,
                )
            continue

        email = normalize_email(email)

        existing = email_repo.find_one({"message_id": email.message_id})
        if existing and existing.get("processing_status", {}).get("stage") == ProcessingStage.COMPLETED.value:
            results.append(EmailResult(message_id=email.message_id, final_stage="SKIPPED"))
            continue

        email_repo.upsert_by_key(
            {"message_id": email.message_id}, email.model_dump(mode="json", by_alias=True)
        )
        email_repo.set_stage(email.message_id, ProcessingStage.RECEIVED.value)
        email_repo.set_stage(email.message_id, ProcessingStage.VALIDATED.value)

        # Everything below calls out to LLM/provider code and mutates several
        # collections across multiple stages. Any unexpected exception here
        # (timeouts, transport errors, ...) must not crash the whole batch --
        # it is recorded as a FAILED result at whatever stage was in flight,
        # and the loop moves on to the next email.
        current_stage = ProcessingStage.THREADED
        try:
            candidates = _load_thread_candidates(thread_repo)
            thread_id = resolve_thread_id(email, candidates)
            _upsert_thread(thread_repo, thread_id, email)
            email_repo.set_stage(email.message_id, ProcessingStage.THREADED.value)

            current_stage = ProcessingStage.ANALYZED
            outcome = analyze_email_with_validation(llm_provider, email)
            if not outcome.success:
                email_repo.set_stage(
                    email.message_id,
                    ProcessingStage.FAILED.value,
                    error=outcome.error,
                    failed_stage=ProcessingStage.ANALYZED.value,
                )
                results.append(EmailResult(message_id=email.message_id, final_stage="FAILED", error=outcome.error))
                continue
            analysis = outcome.analysis
            email_repo.set_stage(email.message_id, ProcessingStage.ANALYZED.value)

            current_stage = ProcessingStage.CONTEXT_BUILT
            existing_snapshot = context_repo.find_one(
                {"thread_id": thread_id, "triggering_email_id": email.message_id}
            )
            if existing_snapshot:
                next_context = ThreadContext.model_validate(existing_snapshot["context"])
            else:
                previous_snapshot = context_repo.latest_for_thread(thread_id)
                previous_context = (
                    ThreadContext.model_validate(previous_snapshot["context"]) if previous_snapshot else None
                )
                next_context, changes = build_next_context(
                    previous_context, analysis, email.message_id, llm_provider
                )
                next_version = (previous_snapshot["context_version"] + 1) if previous_snapshot else 1
                context_repo.upsert_by_key(
                    {"thread_id": thread_id, "triggering_email_id": email.message_id},
                    {
                        "thread_id": thread_id,
                        "context_version": next_version,
                        "triggering_email_id": email.message_id,
                        "context": next_context.model_dump(mode="json"),
                        "changes_from_previous_context": [c.model_dump(mode="json") for c in changes],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            email_repo.set_stage(email.message_id, ProcessingStage.CONTEXT_BUILT.value)

            current_stage = ProcessingStage.KNOWLEDGE_PROCESSED
            _process_knowledge(
                knowledge_repo,
                thread_id,
                analysis,
                llm_provider,
                thread_id,
                email.message_id,
                datetime.now(timezone.utc),
            )
            email_repo.set_stage(email.message_id, ProcessingStage.KNOWLEDGE_PROCESSED.value)

            current_stage = ProcessingStage.ENTITIES_PROCESSED
            # email.timestamp, not datetime.now() -- matches detect_meeting's existing
            # reference-date pattern, so relative phrases resolve consistently regardless
            # of when the pipeline actually runs.
            entities_referenced = _process_entities(db, thread_id, email, analysis, email.timestamp)
            source_link = (
                f"https://mail.google.com/mail/u/0/#all/{email.message_id}"
                if _GMAIL_INTERNAL_ID_PATTERN.match(email.message_id)
                else None
            )
            email_repo.set_entity_metadata(
                message_id=email.message_id,
                record_id=email.message_id,
                source_type="gmail",
                source_link=source_link,
                date=email.timestamp.date().isoformat(),
                entities_referenced=entities_referenced,
                goal_pillar=analysis.goal_pillar,
                label_applied=analysis.label_applied,
                confidence=analysis.confidence,
            )
            email_repo.set_stage(email.message_id, ProcessingStage.ENTITIES_PROCESSED.value)

            current_stage = ProcessingStage.REPLY_PROCESSED
            # email.from_.email is already lowercased by normalize_email; lowercase
            # settings.agent_email too so the comparison is case-insensitive regardless of
            # how the operator wrote it in .env. An email FROM our own mailbox (e.g. the
            # sales rep's own outbound message in a two-sided demo thread) must never get a
            # reply draft generated for it.
            is_from_agent = email.from_.email.lower() == settings.agent_email.lower()
            if not is_from_agent and needs_reply(analysis, email):
                reply_key = {"source_email_id": email.message_id}
                # A reply draft may already exist for this email (e.g. a human
                # already approved/edited/sent it after an earlier partial run).
                # Never blind-overwrite it -- only create it the first time.
                if reply_repo.find_one(reply_key) is None:
                    draft_content = draft_reply(llm_provider, next_context, email)
                    draft = ReplyDraft(
                        reply_id=f"reply_{email.message_id}",
                        thread_id=thread_id,
                        source_email_id=email.message_id,
                        status="awaiting_approval",
                        draft=draft_content,
                    )
                    reply_repo.upsert_by_key(reply_key, draft.model_dump(mode="json"))
            email_repo.set_stage(email.message_id, ProcessingStage.REPLY_PROCESSED.value)

            current_stage = ProcessingStage.MEETING_PROCESSED
            detection = detect_meeting(email, thread_id, settings.timezone, email.timestamp)
            action = build_calendar_action(detection, thread_id, reference_now=email.timestamp)
            if action is not None:
                calendar_key = {
                    "thread_id": action.thread_id,
                    "meeting_fingerprint": action.meeting_fingerprint,
                }
                # Same guard as reply_drafts above: a calendar action for this
                # key may already have been approved/scheduled by a human, and
                # must never be blind-overwritten by a later run.
                if calendar_repo.find_one(calendar_key) is None:
                    calendar_repo.upsert_by_key(calendar_key, action.model_dump(mode="json"))
            email_repo.set_stage(email.message_id, ProcessingStage.MEETING_PROCESSED.value)

            email_repo.set_stage(email.message_id, ProcessingStage.COMPLETED.value)
            results.append(EmailResult(message_id=email.message_id, final_stage="COMPLETED"))
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any provider/stage failure must not crash the batch
            error_detail = f"{type(exc).__name__}: {exc}"
            email_repo.set_stage(
                email.message_id,
                ProcessingStage.FAILED.value,
                error=error_detail,
                failed_stage=current_stage.value,
            )
            results.append(EmailResult(message_id=email.message_id, final_stage="FAILED", error=error_detail))
            continue

    completed_at = datetime.now(timezone.utc)
    summary = PipelineRunSummary(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        processed=len(raw_emails),
        completed=sum(1 for r in results if r.final_stage == "COMPLETED"),
        failed=sum(1 for r in results if r.final_stage == "FAILED"),
        skipped=sum(1 for r in results if r.final_stage == "SKIPPED"),
        results=results,
    )
    run_repo.upsert_by_key({"run_id": run_id}, summary.model_dump(mode="json"))
    return summary
