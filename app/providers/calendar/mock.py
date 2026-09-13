import uuid

from app.calendar.models import CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class MockCalendarProvider(CalendarProvider):
    def __init__(self):
        self.created_events: list[CalendarEvent] = []

    def create_event(self, event: CalendarEvent) -> str:
        self.created_events.append(event)
        return f"mock_event_{uuid.uuid4().hex[:12]}"
