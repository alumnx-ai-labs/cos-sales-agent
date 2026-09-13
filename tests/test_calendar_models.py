import pytest
from pydantic import ValidationError

from app.calendar.models import CalendarEvent


def _base_kwargs(**overrides):
    kwargs = dict(
        title="ABC Corp Sales Discussion",
        start="2026-09-15T15:00:00+05:30",
        end="2026-09-15T16:00:00+05:30",
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    kwargs.update(overrides)
    return kwargs


def test_calendar_event_defaults_to_no_attendees():
    event = CalendarEvent(**_base_kwargs())
    assert event.attendees == []


def test_calendar_event_rejects_external_attendees():
    with pytest.raises(ValidationError):
        CalendarEvent(**_base_kwargs(attendees=["customer@example.com"]))
