from typing import Any

from app.calendar.models import CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class MCPCalendarProvider(CalendarProvider):
    """Adapter around an MCP calendar server connection. See MCPEmailProvider docstring."""

    def __init__(self, client: Any = None):
        self._client = client

    def create_event(self, event: CalendarEvent) -> str:
        if self._client is None:
            raise RuntimeError(
                "MCP calendar provider is not configured — set MCP_CALENDAR_ENABLED=true and "
                "provide a server connection"
            )
        assert event.attendees == [], "external attendees must never reach a calendar provider"
        return self._client.create_event(event.model_dump(mode="json"))
