from datetime import datetime, timezone

from app.calendar.detector import detect_meeting
from app.email.models import parse_email


def _email(body: str):
    return parse_email(
        {
            "message_id": "msg_005",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": "Meeting request",
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_detects_explicit_meeting_with_day_time_and_duration():
    result = detect_meeting(
        _email("Let's meet Tuesday at 3 PM for 30 minutes."),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is True
    assert result.needs_clarification is False
    assert result.start is not None
    assert (result.end - result.start).total_seconds() == 30 * 60


def test_detects_meeting_with_default_duration_when_unspecified():
    result = detect_meeting(
        _email("Can we have a call tomorrow at 11?"),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is True
    assert (result.end - result.start).total_seconds() == 30 * 60


def test_ambiguous_request_needs_clarification():
    result = detect_meeting(
        _email("Maybe next week sometime?"),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is False
    assert result.needs_clarification is True
    assert result.missing_information


def test_no_meeting_language_returns_not_detected():
    result = detect_meeting(
        _email("Thanks for the update, looks good."),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is False
    assert result.needs_clarification is False


def test_ambiguous_phrase_with_coincidental_day_and_time_does_not_fabricate_meeting():
    # "soon" is an ambiguous-phrase word, and "Friday" / "3pm" appear in the
    # sentence, but there is no meeting verb (meet/call/sync/discussion/
    # chat) at all -- this is not a scheduling request and must not be
    # stitched into a fabricated meeting via the coincidental day/time.
    result = detect_meeting(
        _email("Following up on the Friday 3pm deadline for the report -- I will circle back soon."),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is False
    assert result.needs_clarification is True
    assert result.missing_information
    assert result.start is None
    assert result.title is None
