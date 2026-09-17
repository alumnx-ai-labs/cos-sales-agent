# tests/test_entities_resolution.py
from datetime import datetime, timezone

import mongomock
import pytest

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)
from app.entities.resolution import (
    derive_follow_up,
    resolve_commitment,
    resolve_meeting,
    resolve_person,
    resolve_personal_item,
    resolve_project,
)

_NOW = datetime(2026, 9, 13, 10, 30, tzinfo=timezone.utc)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_resolve_person_merges_on_exact_email(db):
    first = resolve_person(db, {"name": "Jane", "email": "jane@example.com"}, is_sender=True, now=_NOW)
    second = resolve_person(db, {"name": "Jane Doe", "email": "Jane@Example.com"}, is_sender=True, now=_NOW)

    assert first == second
    assert PersonRepository(db).find_many({}).__len__() == 1


def test_resolve_person_never_merges_on_name_alone_and_flags_for_review(db):
    first = resolve_person(db, {"name": "Sam Lee", "email": None}, is_sender=None, now=_NOW)
    second = resolve_person(db, {"name": "Sam Lee", "email": None}, is_sender=None, now=_NOW)

    assert first != second
    people = PersonRepository(db).find_many({})
    assert len(people) == 2
    assert all(p["review_flag"] is True for p in people)
    # The "email" key must be OMITTED (not stored as null) for a no-email Person -- a
    # sparse unique index on real MongoDB only excludes a document where the field is
    # entirely missing, not one where it is present with value null. Storing "email": null
    # for two such People would collide on people.email's sparse-unique index (Task 3) on
    # real MongoDB, even though mongomock's more lenient interpretation would not catch it.
    assert all("email" not in p for p in people)


def test_resolve_person_touches_last_inbound_when_sender(db):
    person_id = resolve_person(db, {"name": "Jane", "email": "jane@example.com"}, is_sender=True, now=_NOW)
    stored = PersonRepository(db).find_one({"id": person_id})
    assert stored["last_inbound"] is not None
    assert stored["last_outbound"] is None


def test_resolve_project_merges_on_exact_name_entity_and_goal_pillar(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "renewal", "org": "Acme"}, goal_pillar="Sales")

    assert first == second
    assert len(ProjectRepository(db).find_many({})) == 1


def test_resolve_project_does_not_merge_across_different_entities(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "Renewal", "org": "OtherCo"}, goal_pillar="Sales")

    assert first != second


def test_resolve_project_does_not_merge_without_goal_pillar_corroboration(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Support")

    assert first != second


def test_resolve_commitment_deduplicates_within_same_thread(db):
    raw = {"what": "Send updated case study", "class": "mine", "date_phrase": None}
    first = resolve_commitment(
        db, thread_id="thread_1", raw=raw, message_id="msg_001", made_on=_NOW,
        resolved_date=None, date_type=None, goal_pillar="Sales", project_id=None,
    )
    second = resolve_commitment(
        db, thread_id="thread_1", raw={"what": "send updated case study", "class": "mine", "date_phrase": None},
        message_id="msg_002", made_on=_NOW, resolved_date=None, date_type=None,
        goal_pillar="Sales", project_id=None,
    )

    assert first == second
    assert len(CommitmentRepository(db).all_for_thread("thread_1")) == 1


def test_resolve_commitment_creates_new_for_different_date(db):
    raw_a = {"what": "Send case study", "class": "mine", "date_phrase": None}
    first = resolve_commitment(
        db, thread_id="thread_1", raw=raw_a, message_id="msg_001", made_on=_NOW,
        resolved_date=datetime(2026, 9, 20, tzinfo=timezone.utc), date_type="inferred",
        goal_pillar="Sales", project_id=None,
    )
    second = resolve_commitment(
        db, thread_id="thread_1", raw=raw_a, message_id="msg_002", made_on=_NOW,
        resolved_date=datetime(2026, 9, 27, tzinfo=timezone.utc), date_type="inferred",
        goal_pillar="Sales", project_id=None,
    )

    assert first != second


def test_resolve_meeting_deduplicates_on_thread_and_date(db):
    date = datetime(2026, 9, 20, tzinfo=timezone.utc)
    first = resolve_meeting(
        db, thread_id="thread_1", date=date, raw={"attendees": [], "actions_raised": []}, actionable=True
    )
    second = resolve_meeting(
        db, thread_id="thread_1", date=date, raw={"attendees": [], "actions_raised": []}, actionable=True
    )

    assert first == second
    assert len(MeetingRepository(db).all_for_thread("thread_1")) == 1


def test_resolve_meeting_stores_actionable_flag(db):
    meeting_id = resolve_meeting(
        db, thread_id="thread_2", date=None, raw={"attendees": [], "actions_raised": []}, actionable=False
    )
    stored = MeetingRepository(db).find_one({"id": meeting_id})
    assert stored["actionable"] is False


def test_resolve_personal_item_deduplicates_on_sender_and_description(db):
    raw = {"item_type": "reminder", "description": "Renew passport"}
    first = resolve_personal_item(db, sender_email="jane@example.com", raw=raw, resolved_date=None)
    second = resolve_personal_item(db, sender_email="Jane@Example.com", raw={"item_type": "reminder", "description": "renew passport"}, resolved_date=None)

    assert first == second
    assert len(PersonalItemRepository(db).find_many({})) == 1


def test_derive_follow_up_from_commitment_is_idempotent(db):
    first = derive_follow_up(db, commitment_id="COM-001", thread_id=None)
    second = derive_follow_up(db, commitment_id="COM-001", thread_id=None)

    assert first == second
    stored = FollowUpRepository(db).find_one({"id": first})
    assert stored["commitment_id"] == "COM-001"
    assert stored["thread_id"] is None


def test_derive_follow_up_from_thread_when_no_commitment(db):
    follow_up_id = derive_follow_up(db, commitment_id=None, thread_id="thread_1")
    stored = FollowUpRepository(db).find_one({"id": follow_up_id})
    assert stored["thread_id"] == "thread_1"
    assert stored["commitment_id"] is None
