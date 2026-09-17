# app/entities/resolution.py
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from pymongo.database import Database

from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)
from app.entities.ids import next_id
from app.entities.models import Commitment, FollowUp, Meeting, Person, PersonalItem, Project
from app.knowledge.normalize import normalize_text

# Serializes a datetime exactly the way Person.model_dump(mode="json") would (e.g. a
# tz-aware UTC value as "...Z", not datetime.isoformat()'s "...+00:00"), without assuming
# `now` is guaranteed UTC-aware -- so the update path below matches the creation path's
# format regardless of what tzinfo (or lack of one) `now` actually carries.
_DATETIME_JSON = TypeAdapter(datetime)


def _parse_iso(value: str | None) -> datetime | None:
    # pydantic's model_dump(mode="json") serializes a tz-aware UTC datetime with a
    # trailing "Z" (e.g. "...T00:00:00Z"), while Python's own datetime.isoformat()
    # produces "...+00:00" for the same instant. Comparing those two string forms
    # directly (as the original spec's code did) breaks the "exact match" dedup rule
    # for any non-null date, since two representations of the identical instant would
    # never compare equal as strings. Parsing back to a datetime for comparison makes
    # the equality check instant-based rather than string-format-based, which is what
    # "exact natural-key match" actually requires.
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_person(
    db: Database, mention: dict[str, Any], is_sender: bool | None, now: datetime
) -> str:
    repo = PersonRepository(db)
    email = (mention.get("email") or "").strip().lower() or None

    if email:
        existing = repo.find_one({"email": email})
        if existing:
            update: dict[str, Any] = {}
            if is_sender is True:
                update["last_inbound"] = _DATETIME_JSON.dump_python(now, mode="json")
            elif is_sender is False:
                update["last_outbound"] = _DATETIME_JSON.dump_python(now, mode="json")
            if update:
                repo.upsert_by_key({"id": existing["id"]}, {**existing, **update})
            return existing["id"]

        person_id = next_id(db, "PER-")
        person = Person(
            id=person_id,
            name=mention.get("name") or email,
            email=email,
            org=mention.get("org"),
            review_flag=False,
            last_inbound=now if is_sender is True else None,
            last_outbound=now if is_sender is False else None,
        )
        repo.upsert_by_key({"id": person_id}, person.model_dump(mode="json"))
        return person_id

    # No email present: never merge on name alone -- always create new, flagged for review.
    person_id = next_id(db, "PER-")
    person = Person(
        id=person_id,
        name=mention.get("name") or "Unknown",
        email=None,
        org=mention.get("org"),
        review_flag=True,
    )
    # exclude={"email"}: MongoDB's sparse unique index on people.email (Task 3) only
    # excludes a document where the field is entirely MISSING -- a document with
    # email explicitly set to null still gets indexed with key null, and a second such
    # document would collide on the unique constraint. Omitting the key entirely (rather
    # than storing "email": null) is what actually makes two no-email People coexist on
    # real MongoDB, not just under mongomock's more lenient interpretation of sparse+null.
    repo.upsert_by_key({"id": person_id}, person.model_dump(mode="json", exclude={"email"}))
    return person_id


def resolve_project(db: Database, mention: dict[str, Any], goal_pillar: str) -> str:
    repo = ProjectRepository(db)
    name_normalized = normalize_text(mention["name"])
    entity = mention.get("org")

    candidates = repo.find_many({"entity": entity}) if entity else []
    for candidate in candidates:
        if (
            normalize_text(candidate["project"]) == name_normalized
            and candidate.get("goal_pillar") == goal_pillar
        ):
            return candidate["id"]

    project_id = next_id(db, "PRJ-")
    project = Project(id=project_id, project=mention["name"], entity=entity, goal_pillar=goal_pillar)
    repo.upsert_by_key({"id": project_id}, project.model_dump(mode="json"))
    return project_id


def resolve_commitment(
    db: Database,
    thread_id: str,
    raw: dict[str, Any],
    message_id: str,
    made_on: datetime,
    resolved_date: datetime | None,
    date_type: str | None,
    goal_pillar: str,
    project_id: str | None,
) -> str:
    repo = CommitmentRepository(db)
    what_normalized = normalize_text(raw["what"])

    for candidate in repo.all_for_thread(thread_id):
        if (
            normalize_text(candidate["what"]) == what_normalized
            and candidate["class"] == raw["class"]
            and _parse_iso(candidate.get("committed_date")) == resolved_date
        ):
            return candidate["id"]

    commitment_id = next_id(db, "COM-")
    commitment = Commitment(
        id=commitment_id,
        what=raw["what"],
        commitment_class=raw["class"],
        importance=raw.get("importance_hint"),
        owed_by=raw.get("owed_by"),
        owed_to=raw.get("owed_to"),
        source_record=message_id,
        made_on=made_on,
        committed_date=resolved_date,
        date_type=date_type,
        goal_pillar=goal_pillar,
        project_id=project_id,
    )
    doc = commitment.model_dump(mode="json", by_alias=True)
    doc["thread_id"] = thread_id
    repo.upsert_by_key({"id": commitment_id}, doc)
    return commitment_id


def resolve_meeting(
    db: Database, thread_id: str, date: datetime | None, raw: dict[str, Any], actionable: bool
) -> str:
    repo = MeetingRepository(db)

    for candidate in repo.all_for_thread(thread_id):
        if _parse_iso(candidate.get("date")) == date:
            return candidate["id"]

    meeting_id = next_id(db, "MTG-")
    meeting = Meeting(
        id=meeting_id,
        date=date,
        attendees=raw.get("attendees", []),
        actions_raised=raw.get("actions_raised", []),
        actionable=actionable,
    )
    doc = meeting.model_dump(mode="json")
    doc["thread_id"] = thread_id
    repo.upsert_by_key({"id": meeting_id}, doc)
    return meeting_id


def resolve_personal_item(
    db: Database, sender_email: str, raw: dict[str, Any], resolved_date: datetime | None
) -> str:
    repo = PersonalItemRepository(db)
    sender_normalized = sender_email.strip().lower()
    description_normalized = normalize_text(raw["description"])

    for candidate in repo.find_many({"sender_email": sender_normalized}):
        if normalize_text(candidate["description"]) == description_normalized:
            return candidate["id"]

    item_id = next_id(db, "PSN-")
    item = PersonalItem(
        id=item_id,
        type=raw["item_type"],
        description=raw["description"],
        date_or_deadline=resolved_date,
    )
    doc = item.model_dump(mode="json")
    doc["sender_email"] = sender_normalized
    repo.upsert_by_key({"id": item_id}, doc)
    return item_id


def derive_follow_up(db: Database, commitment_id: str | None, thread_id: str | None) -> str:
    repo = FollowUpRepository(db)

    if commitment_id is not None:
        existing = repo.find_one({"commitment_id": commitment_id})
        if existing:
            return existing["id"]
        follow_up_id = next_id(db, "FU-")
        follow_up = FollowUp(id=follow_up_id, commitment_id=commitment_id)
        repo.upsert_by_key({"id": follow_up_id}, follow_up.model_dump(mode="json"))
        return follow_up_id

    existing = repo.find_one({"thread_id": thread_id})
    if existing:
        return existing["id"]
    follow_up_id = next_id(db, "FU-")
    follow_up = FollowUp(id=follow_up_id, thread_id=thread_id)
    repo.upsert_by_key({"id": follow_up_id}, follow_up.model_dump(mode="json"))
    return follow_up_id
