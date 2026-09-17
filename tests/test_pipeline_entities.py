import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    PersonRepository,
)
from app.pipeline import run_pipeline
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.email.mock import MockEmailProvider
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


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


@pytest.fixture
def settings():
    return Settings(email_provider="mock", calendar_provider="mock", llm_provider="mock")


def test_pipeline_populates_entity_metadata_on_the_email(db, settings):
    payloads = [_raw_email("1a08090646ebaa45", "I will send the proposal on Friday.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    assert stored["record_id"] == "1a08090646ebaa45"
    assert stored["source_type"] == "gmail"
    assert stored["source_link"] == "https://mail.google.com/mail/u/0/#all/1a08090646ebaa45"
    assert stored["date"] == "2026-09-13"
    assert stored["goal_pillar"] == "Sales"
    assert stored["label_applied"] in {"Needs reply: ASAP", "Read only"}
    assert isinstance(stored["confidence"], float)

    entities_referenced = stored["entities_referenced"]
    assert len(entities_referenced["people"]) == 1
    assert len(entities_referenced["commitments"]) == 1
    assert len(entities_referenced["follow_ups"]) == 1
    assert entities_referenced["projects"] == []
    assert entities_referenced["meetings"] == []
    assert entities_referenced["personal"] == []

    person = PersonRepository(db).find_one({"id": entities_referenced["people"][0]})
    assert person["email"] == "john@example.com"

    commitment = CommitmentRepository(db).find_one({"id": entities_referenced["commitments"][0]})
    assert commitment["class"] == "mine"

    follow_up = FollowUpRepository(db).find_one({"id": entities_referenced["follow_ups"][0]})
    assert follow_up["commitment_id"] == entities_referenced["commitments"][0]


def test_pipeline_sets_source_link_to_none_for_non_gmail_shaped_message_id(db, settings):
    payloads = [_raw_email("not-a-gmail-hex-id", "Just checking in.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "not-a-gmail-hex-id"}, {"_id": 0})
    assert stored["source_link"] is None


def test_pipeline_reuses_same_person_across_two_emails_in_same_thread(db, settings):
    payloads = [
        _raw_email("1111111111111111", "I will send the proposal on Friday."),
        _raw_email(
            "2222222222222222",
            "Following up on my earlier note.",
            in_reply_to="1111111111111111",
            references=["1111111111111111"],
        ),
    ]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    assert PersonRepository(db).find_many({}).__len__() == 1


def test_pipeline_detects_relative_date_meeting_with_no_commitment_and_no_follow_up(db, settings):
    from app.database.repositories import FollowUpRepository, MeetingRepository

    payloads = [_raw_email("1a08090646ebaa45", "Sounds good. We will meet in 2 weeks.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    entities_referenced = stored["entities_referenced"]
    assert entities_referenced["commitments"] == []
    assert len(entities_referenced["meetings"]) == 1

    meeting = MeetingRepository(db).find_one({"id": entities_referenced["meetings"][0]})
    assert meeting["actionable"] is True
    # 2026-09-13 (this email's timestamp) + 14 days = 2026-09-27
    assert meeting["date"].startswith("2026-09-27")

    # The core corrected rule: a Meeting must never trigger a FollowUp by itself.
    assert entities_referenced["follow_ups"] == []
    assert FollowUpRepository(db).find_many({}) == []


def test_pipeline_does_not_mark_historical_meeting_mention_as_actionable(db, settings):
    payloads = [_raw_email("1a08090646ebaa45", "We met last week and it went well.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    # MockLLMProvider never recognizes "met" (past tense) as a meeting mention at all --
    # see test_mock_llm_does_not_detect_historical_meeting_mention_as_a_meeting (Task 5).
    assert stored["entities_referenced"]["meetings"] == []


def test_pipeline_marks_failed_at_entities_processed_without_losing_prior_stage_data(
    db, settings, monkeypatch
):
    # A shape-invalid EmailAnalysis field would fail pydantic validation during the
    # existing ANALYZED stage (inside analyze_email_with_validation), not the new
    # ENTITIES_PROCESSED stage -- that would test the wrong stage entirely. To reach a
    # failure specifically inside the new stage, the EmailAnalysis must validate
    # successfully; the failure must come from entity resolution itself. Monkeypatching
    # the resolver app/pipeline.py actually calls is the precise way to do that.
    import app.pipeline as pipeline_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated entity resolution failure")

    monkeypatch.setattr(pipeline_module, "resolve_person", _boom)

    payloads = [_raw_email("1a08090646ebaa45", "I will send the proposal on Friday.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    assert stored["processing_status"]["stage"] == "FAILED"
    assert stored["processing_status"]["failed_stage"] == "ENTITIES_PROCESSED"
    assert "simulated entity resolution failure" in stored["processing_status"]["error"]
    # Knowledge/context from earlier stages must still be persisted, not rolled back.
    assert db.context_snapshots.count_documents({}) == 1
    assert db.knowledge_items.count_documents({}) >= 1
