from datetime import datetime, timezone

import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.interfaces.email_provider import EmailProvider
from app.interfaces.llm_provider import LLMProvider
from app.pipeline import run_pipeline
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.llm.mock import MockLLMProvider


def _raw_email(message_id, body, subject="Enterprise CRM Proposal", **overrides):
    raw = {
        "message_id": message_id,
        "from": {"name": "John", "email": "john@example.com"},
        "to": [{"name": "Ashok", "email": "ashok@example.com"}],
        "subject": subject,
        "body": body,
        "timestamp": "2026-09-13T10:30:00Z",
    }
    raw.update(overrides)
    return raw


class _ListEmailProvider(EmailProvider):
    def __init__(self, payloads):
        self._payloads = payloads

    def fetch_emails(self, limit):
        return self._payloads[:limit]

    def send_email(self, to, subject, body):
        raise AssertionError("pipeline must never call send_email directly")


class _AlwaysBrokenLLM(LLMProvider):
    def analyze_email(self, email):
        return {"summary": "not enough fields"}

    def update_context(self, previous_context, new_analysis):
        raise AssertionError("should not be reached when analysis fails")

    def verify_same_fact(self, existing_value, new_value, subject, predicate):
        raise AssertionError

    def draft_reply(self, context, latest_email):
        raise AssertionError


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


@pytest.fixture
def settings():
    return Settings(email_provider="mock", calendar_provider="mock", llm_provider="mock")


def test_pipeline_processes_valid_emails_to_completion(db, settings):
    payloads = [
        _raw_email("msg_001", "We currently use Salesforce but pricing is a pain point."),
        _raw_email("msg_002", "We'd need about 100 seats to start.", in_reply_to="msg_001", references=["msg_001"]),
    ]
    summary = run_pipeline(
        db=db,
        email_provider=_ListEmailProvider(payloads),
        llm_provider=MockLLMProvider(),
        calendar_provider=MockCalendarProvider(),
        settings=settings,
    )

    assert summary.processed == 2
    assert summary.completed == 2
    assert summary.failed == 0
    assert db.emails.count_documents({}) == 2
    assert db.threads.count_documents({}) == 1
    assert db.context_snapshots.count_documents({}) == 2
    assert db.knowledge_items.count_documents({}) >= 1

    stored_email = db.emails.find_one({"message_id": "msg_001"})
    assert stored_email["processing_status"]["stage"] == "COMPLETED"


def test_pipeline_is_idempotent_on_rerun(db, settings):
    payloads = [_raw_email("msg_001", "We currently use Salesforce but pricing is a pain point.")]
    email_provider = _ListEmailProvider(payloads)

    first = run_pipeline(db, email_provider, MockLLMProvider(), MockCalendarProvider(), settings)
    second = run_pipeline(db, email_provider, MockLLMProvider(), MockCalendarProvider(), settings)

    assert first.completed == 1
    assert second.skipped == 1
    assert second.completed == 0
    assert db.context_snapshots.count_documents({}) == 1
    assert db.emails.count_documents({}) == 1


def test_pipeline_continues_after_malformed_email_with_no_message_id(db, settings):
    payloads = [
        {"subject": "broken, no message_id at all"},
        _raw_email("msg_002", "We currently use Salesforce."),
    ]
    summary = run_pipeline(
        db, _ListEmailProvider(payloads), MockLLMProvider(), MockCalendarProvider(), settings
    )

    assert summary.completed == 1
    assert summary.failed == 1
    assert db.emails.count_documents({}) == 1  # malformed item never reached the emails collection
    run_doc = db.processing_runs.find_one({"run_id": summary.run_id})
    assert any(r["final_stage"] == "FAILED" and r["message_id"] is None for r in run_doc["results"])


def test_pipeline_marks_analysis_failure_without_completing(db, settings):
    payloads = [_raw_email("msg_001", "Some body text.")]
    summary = run_pipeline(
        db, _ListEmailProvider(payloads), _AlwaysBrokenLLM(), MockCalendarProvider(), settings
    )

    assert summary.failed == 1
    assert summary.completed == 0
    stored_email = db.emails.find_one({"message_id": "msg_001"})
    assert stored_email["processing_status"]["stage"] == "FAILED"
    assert stored_email["processing_status"]["failed_stage"] == "ANALYZED"
    assert db.context_snapshots.count_documents({}) == 0
