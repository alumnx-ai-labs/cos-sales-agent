from datetime import datetime, timezone

import mongomock

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ReplyDraftRepository,
    ThreadRepository,
)
from app.ui.data import (
    dashboard_metrics,
    list_calendar_actions,
    list_emails,
    list_knowledge,
    list_reply_drafts,
    list_threads,
    thread_context_versions,
)


def _db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_dashboard_metrics_counts_each_collection():
    db = _db()
    EmailRepository(db).upsert_by_key({"message_id": "msg_001"}, {"message_id": "msg_001"})
    ThreadRepository(db).upsert_by_key({"thread_id": "t1"}, {"thread_id": "t1"})
    KnowledgeRepository(db).upsert_by_key(
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
    )
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_001"}, {"source_email_id": "msg_001", "status": "awaiting_approval"}
    )
    CalendarActionRepository(db).upsert_by_key(
        {"thread_id": "t1", "meeting_fingerprint": "fp1"},
        {"thread_id": "t1", "meeting_fingerprint": "fp1", "status": "awaiting_approval"},
    )

    metrics = dashboard_metrics(db)
    assert metrics["emails_processed"] == 1
    assert metrics["threads"] == 1
    assert metrics["knowledge_items"] == 1
    assert metrics["pending_replies"] == 1
    assert metrics["pending_calendar_actions"] == 1


def test_list_emails_and_threads_return_stored_documents():
    db = _db()
    EmailRepository(db).upsert_by_key({"message_id": "msg_001"}, {"message_id": "msg_001", "subject": "Hi"})
    ThreadRepository(db).upsert_by_key({"thread_id": "t1"}, {"thread_id": "t1"})

    assert list_emails(db)[0]["subject"] == "Hi"
    assert list_threads(db)[0]["thread_id"] == "t1"


def test_thread_context_versions_ordered_ascending():
    db = _db()
    repo = ContextSnapshotRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_002"},
        {"thread_id": "t1", "triggering_email_id": "msg_002", "context_version": 2},
    )
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_001"},
        {"thread_id": "t1", "triggering_email_id": "msg_001", "context_version": 1},
    )
    versions = [snap["context_version"] for snap in thread_context_versions(db, "t1")]
    assert versions == [1, 2]


def test_list_knowledge_filters_by_thread():
    db = _db()
    repo = KnowledgeRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
    )
    repo.upsert_by_key(
        {"thread_id": "t2", "subject_key": "xyz", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t2", "subject_key": "xyz", "predicate": "requires", "fact_key": "seat_count"},
    )
    assert len(list_knowledge(db, thread_id="t1")) == 1
    assert len(list_knowledge(db)) == 2


def test_list_reply_drafts_and_calendar_actions_filter_by_status():
    db = _db()
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_001"}, {"source_email_id": "msg_001", "status": "awaiting_approval"}
    )
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_002"}, {"source_email_id": "msg_002", "status": "simulated_sent"}
    )
    CalendarActionRepository(db).upsert_by_key(
        {"thread_id": "t1", "meeting_fingerprint": "fp1"},
        {"thread_id": "t1", "meeting_fingerprint": "fp1", "status": "needs_clarification"},
    )

    assert len(list_reply_drafts(db, status="awaiting_approval")) == 1
    assert len(list_reply_drafts(db)) == 2
    assert len(list_calendar_actions(db, status="needs_clarification")) == 1
