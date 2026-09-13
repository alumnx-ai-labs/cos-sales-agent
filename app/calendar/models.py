from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CalendarEvent(BaseModel):
    title: str
    start: datetime
    end: datetime
    timezone: str
    description: str
    attendees: list[str] = Field(default_factory=list)

    @field_validator("attendees")
    @classmethod
    def validate_no_external_attendees(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("External attendees are not permitted")
        return value


class CalendarAction(BaseModel):
    thread_id: str
    meeting_fingerprint: str
    status: Literal[
        "pending", "awaiting_approval", "approved", "scheduled", "failed", "rejected", "needs_clarification"
    ]
    event: CalendarEvent
    actor_type: Literal["authenticated_user"] = "authenticated_user"
    reason: str | None = None
