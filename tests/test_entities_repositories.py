import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_person_repository_upsert_and_email_uniqueness(db):
    repo = PersonRepository(db)
    repo.upsert_by_key({"id": "PER-001"}, {"id": "PER-001", "name": "Jane", "email": "jane@example.com"})

    with pytest.raises(DuplicateKeyError):
        db.people.insert_one({"id": "PER-002", "name": "Jane Two", "email": "jane@example.com"})


def test_person_repository_allows_multiple_people_with_no_email(db):
    db.people.insert_one({"id": "PER-003", "name": "Unknown One", "email": None})
    db.people.insert_one({"id": "PER-004", "name": "Unknown Two", "email": None})

    assert db.people.count_documents({}) == 2


def test_project_repository_upsert_is_idempotent(db):
    repo = ProjectRepository(db)
    repo.upsert_by_key({"id": "PRJ-001"}, {"id": "PRJ-001", "project": "Renewal"})
    repo.upsert_by_key({"id": "PRJ-001"}, {"id": "PRJ-001", "project": "Renewal", "status": "active"})

    assert db.projects.count_documents({}) == 1
    assert repo.find_one({"id": "PRJ-001"})["status"] == "active"


def test_commitment_repository_all_for_thread(db):
    repo = CommitmentRepository(db)
    repo.upsert_by_key(
        {"id": "COM-001"},
        {"id": "COM-001", "thread_id": "thread_1", "what": "send case study"},
    )
    repo.upsert_by_key(
        {"id": "COM-002"},
        {"id": "COM-002", "thread_id": "thread_2", "what": "unrelated"},
    )

    results = repo.all_for_thread("thread_1")
    assert len(results) == 1
    assert results[0]["id"] == "COM-001"


def test_follow_up_repository_upsert(db):
    repo = FollowUpRepository(db)
    repo.upsert_by_key({"id": "FU-001"}, {"id": "FU-001", "commitment_id": "COM-001", "thread_id": None})
    assert repo.find_one({"id": "FU-001"})["commitment_id"] == "COM-001"


def test_meeting_repository_all_for_thread(db):
    repo = MeetingRepository(db)
    repo.upsert_by_key({"id": "MTG-001"}, {"id": "MTG-001", "thread_id": "thread_1"})
    results = repo.all_for_thread("thread_1")
    assert len(results) == 1


def test_personal_item_repository_upsert(db):
    repo = PersonalItemRepository(db)
    repo.upsert_by_key({"id": "PSN-001"}, {"id": "PSN-001", "type": "reminder", "description": "x"})
    assert db.personal_items.count_documents({}) == 1
