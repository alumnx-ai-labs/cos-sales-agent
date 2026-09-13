from datetime import datetime, timezone

from app.calendar.models import CalendarEvent
from app.providers.calendar.mock import MockCalendarProvider


def test_mock_calendar_provider_records_created_events():
    provider = MockCalendarProvider()
    event = CalendarEvent(
        title="Sales Call",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 15, 30, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="desc",
    )
    event_id = provider.create_event(event)
    assert event_id.startswith("mock_event_")
    assert provider.created_events == [event]
