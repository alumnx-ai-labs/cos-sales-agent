from typing import Any

from pymongo.database import Database

from app.config.settings import Settings
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ReplyDraftRepository,
    ThreadRepository,
)
from app.email.models import Email
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.llm_provider import LLMProvider
from app.pipeline import run_pipeline
from app.providers.email.mock import MockEmailProvider

_PENDING_CALENDAR_STATUSES = ("awaiting_approval", "needs_clarification")
_BODY_PREVIEW_LENGTH = 150


def _empty_result(status: str, error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "error": error,
        "thread_id": None,
        "context_summary": None,
        "knowledge": [],
        "reply_draft": None,
        "calendar_proposal": None,
    }


def process_email(
    db: Database,
    email: Email,
    llm_provider: LLMProvider,
    calendar_provider: CalendarProvider,
    settings: Settings,
) -> dict[str, Any]:
    raw = email.model_dump(mode="json", by_alias=True)
    provider = MockEmailProvider(payloads=[raw])
    summary = run_pipeline(db, provider, llm_provider, calendar_provider, settings)

    if not summary.results:
        return _empty_result("failed", "pipeline produced no result for this email")

    result = summary.results[0]

    if result.final_stage == "FAILED":
        return _empty_result("failed", result.error)

    snapshot = ContextSnapshotRepository(db).find_one({"triggering_email_id": email.message_id})
    thread_id = snapshot["thread_id"] if snapshot else None

    knowledge = KnowledgeRepository(db).all_for_thread(thread_id) if thread_id else []
    draft = ReplyDraftRepository(db).find_one({"source_email_id": email.message_id})
    calendar_actions = (
        CalendarActionRepository(db).find_many({"thread_id": thread_id}) if thread_id else []
    )
    pending_calendar = next(
        (a for a in calendar_actions if a["status"] in _PENDING_CALENDAR_STATUSES), None
    )

    return {
        "status": result.final_stage.lower(),
        "error": None,
        "thread_id": thread_id,
        "context_summary": snapshot["context"]["summary"] if snapshot else None,
        "knowledge": [
            {
                "subject_key": k["subject_key"],
                "predicate": k["predicate"],
                "current_value": k["current_value"],
                "basis": k["basis"],
                "confidence": k["confidence"],
            }
            for k in knowledge
        ],
        "reply_draft": draft["draft"] if draft else None,
        "calendar_proposal": (
            {
                "status": pending_calendar["status"],
                "title": pending_calendar["event"]["title"],
                "start": pending_calendar["event"]["start"],
                "end": pending_calendar["event"]["end"],
                "timezone": pending_calendar["event"]["timezone"],
                "reason": pending_calendar.get("reason"),
            }
            if pending_calendar
            else None
        ),
    }


def list_processed_emails(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    thread_id_by_message_id: dict[str, str] = {}
    for thread in ThreadRepository(db).find_many({}):
        for message_id in thread["message_ids"]:
            thread_id_by_message_id[message_id] = thread["thread_id"]

    emails = sorted(
        EmailRepository(db).find_many({}), key=lambda e: e["timestamp"], reverse=True
    )[:limit]

    context_repo = ContextSnapshotRepository(db)
    summary_by_thread_id: dict[str, str | None] = {}

    results: list[dict[str, Any]] = []
    for email in emails:
        thread_id = thread_id_by_message_id.get(email["message_id"])
        if thread_id is not None and thread_id not in summary_by_thread_id:
            snapshot = context_repo.latest_for_thread(thread_id)
            summary_by_thread_id[thread_id] = snapshot["context"]["summary"] if snapshot else None

        results.append(
            {
                "message_id": email["message_id"],
                "thread_id": thread_id,
                "from": email["from"],
                "to": email["to"],
                "cc": email["cc"],
                "subject": email["subject"],
                "timestamp": email["timestamp"],
                "processing_status": {
                    "stage": email["processing_status"]["stage"],
                    "error": email["processing_status"]["error"],
                },
                "summary": summary_by_thread_id.get(thread_id),
                "body_preview": email["body"][:_BODY_PREVIEW_LENGTH],
            }
        )

    return results
