from datetime import datetime, timezone

import pytest

from app.calendar.actions import approve_calendar_action, build_calendar_action, make_fingerprint, reject_calendar_action
from app.calendar.detector import MeetingDetectionResult
from app.calendar.models import CalendarAction, CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class _RecordingCalendarProvider(CalendarProvider):
    def __init__(self):
        self.created_events: list[CalendarEvent] = []

    def create_event(self, event: CalendarEvent) -> str:
        self.created_events.append(event)
        return "provider_event_id_123"


def test_make_fingerprint_is_stable_for_same_meeting():
    start = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    fp1 = make_fingerprint("ABC Corp Sales Discussion", start, end)
    fp2 = make_fingerprint("ABC Corp Sales Discussion", start, end)
    assert fp1 == fp2


def test_build_calendar_action_from_detected_meeting():
    detection = MeetingDetectionResult(
        meeting_detected=True,
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = build_calendar_action(detection, thread_id="thread_001")
    assert action.status == "awaiting_approval"
    assert action.event.attendees == []


def test_build_calendar_action_for_needs_clarification():
    detection = MeetingDetectionResult(meeting_detected=False, needs_clarification=True, missing_information=["date"])
    action = build_calendar_action(detection, thread_id="thread_001")
    assert action.status == "needs_clarification"


def test_build_calendar_action_returns_none_when_no_meeting():
    detection = MeetingDetectionResult(meeting_detected=False, needs_clarification=False)
    assert build_calendar_action(detection, thread_id="thread_001") is None


def test_approve_calendar_action_calls_provider_and_schedules():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    provider = _RecordingCalendarProvider()
    result = approve_calendar_action(action, provider)
    assert result.status == "scheduled"
    assert len(provider.created_events) == 1


def test_approve_calendar_action_fails_closed_if_attendees_smuggled_in():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    # simulate a dict loaded back from MongoDB that bypassed the constructor validator
    tampered = action.model_copy(deep=True)
    object.__setattr__(tampered.event, "attendees", ["external@example.com"])

    provider = _RecordingCalendarProvider()
    result = approve_calendar_action(tampered, provider)

    assert result.status == "failed"
    assert result.reason == "external attendees not permitted"
    assert len(provider.created_events) == 0


def test_reject_calendar_action_sets_rejected_status():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    result = reject_calendar_action(action)
    assert result.status == "rejected"
