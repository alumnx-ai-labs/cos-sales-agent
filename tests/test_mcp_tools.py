import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.email.models import parse_email
from app.interfaces.llm_provider import LLMProvider
from app.mcp.tools import process_email
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
    return Settings(calendar_provider="mock", llm_provider="mock")


def test_process_email_returns_draft_and_knowledge_for_buying_signal(db, settings):
    email = parse_email(
        _raw_email(
            "msg_001",
            "We currently use Salesforce but pricing has become a real pain point. "
            "Could you send over pricing?",
        )
    )

    result = process_email(db, email, MockLLMProvider(), MockCalendarProvider(), settings)

    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["thread_id"] is not None
    assert result["reply_draft"] is not None
    assert result["reply_draft"]["subject"].startswith("Re:")
    assert any(item["current_value"] == "Salesforce" for item in result["knowledge"])
    assert result["calendar_proposal"] is None


def test_process_email_is_idempotent_on_replay(db, settings):
    raw = _raw_email("msg_001", "We currently use Salesforce but pricing is a pain point.")

    first = process_email(db, parse_email(raw), MockLLMProvider(), MockCalendarProvider(), settings)
    second = process_email(db, parse_email(raw), MockLLMProvider(), MockCalendarProvider(), settings)

    assert first["status"] == "completed"
    assert second["status"] == "skipped"
    assert second["thread_id"] == first["thread_id"]
    assert second["knowledge"] == first["knowledge"]


def test_process_email_surfaces_meeting_proposal_without_scheduling_it(db, settings):
    email = parse_email(
        _raw_email("msg_001", "Let's meet Tuesday at 3 PM for 30 minutes to discuss pricing.")
    )
    calendar_provider = MockCalendarProvider()

    result = process_email(db, email, MockLLMProvider(), calendar_provider, settings)

    assert result["status"] == "completed"
    assert result["calendar_proposal"] is not None
    assert result["calendar_proposal"]["status"] == "awaiting_approval"
    assert calendar_provider.created_events == []


def test_process_email_returns_failed_status_with_error_on_analysis_failure(db, settings):
    email = parse_email(_raw_email("msg_001", "Some body text."))

    result = process_email(db, email, _AlwaysBrokenLLM(), MockCalendarProvider(), settings)

    assert result["status"] == "failed"
    assert result["error"] is not None
    assert result["thread_id"] is None
    assert result["knowledge"] == []
    assert result["reply_draft"] is None
    assert result["calendar_proposal"] is None


def test_process_email_returns_failed_status_when_email_limit_yields_no_result(db):
    settings = Settings(calendar_provider="mock", llm_provider="mock", email_limit=0)
    email = parse_email(_raw_email("msg_001", "Some body text."))

    result = process_email(db, email, MockLLMProvider(), MockCalendarProvider(), settings)

    assert result == {
        "status": "failed",
        "error": "pipeline produced no result for this email",
        "thread_id": None,
        "context_summary": None,
        "knowledge": [],
        "reply_draft": None,
        "calendar_proposal": None,
    }
