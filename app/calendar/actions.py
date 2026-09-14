from datetime import datetime

from app.calendar.detector import MeetingDetectionResult
from app.calendar.models import CalendarAction, CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider
from app.knowledge.normalize import normalize_text


def make_fingerprint(title: str, start: datetime, end: datetime) -> str:
    return f"{normalize_text(title).replace(' ', '_')}_{start.isoformat()}_{end.isoformat()}"


def build_calendar_action(
    detection: MeetingDetectionResult, thread_id: str, reference_now: datetime | None = None
) -> CalendarAction | None:
    if detection.needs_clarification:
        # Default to datetime.now().astimezone() only for backward compatibility with any
        # existing caller that doesn't pass reference_now. Callers that care about
        # determinism (e.g. run_pipeline, given DEMO_SEED=42) should pass a stable
        # reference_now (email.timestamp) so the persisted placeholder event is
        # reproducible across runs instead of drifting with wall-clock time.
        now = reference_now if reference_now is not None else datetime.now().astimezone()
        placeholder_event = CalendarEvent(
            title=detection.title or "Meeting (details pending)",
            start=now,
            end=now,
            timezone=detection.timezone or "UTC",
            description=detection.description or "Awaiting clarification from customer",
        )
        return CalendarAction(
            thread_id=thread_id,
            meeting_fingerprint=f"needs_clarification_{thread_id}",
            status="needs_clarification",
            event=placeholder_event,
            reason=", ".join(detection.missing_information) or "ambiguous meeting request",
        )

    if not detection.meeting_detected:
        return None

    event = CalendarEvent(
        title=detection.title,
        start=detection.start,
        end=detection.end,
        timezone=detection.timezone,
        description=detection.description,
    )
    return CalendarAction(
        thread_id=thread_id,
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )


def approve_calendar_action(action: CalendarAction, calendar_provider: CalendarProvider) -> CalendarAction:
    if action.status != "awaiting_approval":
        return action.model_copy(update={"status": "failed", "reason": "action is not awaiting approval"})

    # Defense-in-depth: CalendarEvent already rejects non-empty attendees at
    # construction time via its field_validator, but that validator only
    # runs on the normal constructor path. An event built via
    # model_construct/model_copy, or one whose attendees were set through
    # direct attribute mutation after construction (e.g. rehydrated from a
    # dict loaded back from MongoDB), never re-runs it. Re-check immediately
    # before the calendar provider is ever called, and fail closed rather
    # than silently stripping.
    if action.event.attendees:
        return action.model_copy(update={"status": "failed", "reason": "external attendees not permitted"})

    calendar_provider.create_event(action.event)
    return action.model_copy(update={"status": "scheduled"})


def reject_calendar_action(action: CalendarAction) -> CalendarAction:
    return action.model_copy(update={"status": "rejected"})
