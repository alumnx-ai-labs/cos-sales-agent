from datetime import datetime, timedelta, timezone

from app.email.models import parse_email
from app.email.threading import ThreadCandidate, resolve_thread_id


def _email(**overrides):
    raw = {
        "message_id": "msg_002",
        "from": {"name": "John", "email": "john@example.com"},
        "to": [{"name": "Ashok", "email": "ashok@example.com"}],
        "subject": "Re: Enterprise CRM Proposal",
        "body": "Following up...",
        "timestamp": "2026-09-14T10:30:00Z",
    }
    raw.update(overrides)
    return parse_email(raw)


def test_uses_provider_thread_id_when_present():
    email = _email(thread_id="thread_provider_123")
    assert resolve_thread_id(email, candidates=[]) == "thread_provider_123"


def test_matches_via_in_reply_to():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Unrelated Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email(in_reply_to="msg_001")
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_matches_via_references():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Unrelated",
        participant_emails={"john@example.com"},
        message_ids={"msg_000", "msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email(references=["msg_000"])
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_matches_via_subject_and_participant_overlap():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Enterprise CRM Proposal",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email()  # subject normalizes to same text, no in_reply_to/references
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_falls_back_to_participant_overlap_within_window():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Totally Different Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
    )
    email = _email(subject="A New Subject Entirely")
    assert resolve_thread_id(email, candidates=[candidate], window_days=14) == "thread_001"


def test_participant_overlap_outside_window_creates_new_thread():
    old_time = datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc) - timedelta(days=20)
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Totally Different Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=old_time,
    )
    email = _email(subject="A New Subject Entirely")
    result = resolve_thread_id(email, candidates=[candidate], window_days=14)
    assert result != "thread_001"


def test_no_match_creates_new_thread_id():
    email = _email()
    result = resolve_thread_id(email, candidates=[])
    assert result == "thread_msg_002"
