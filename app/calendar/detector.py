import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.email.models import Email

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_DEFAULT_DURATION_MINUTES = 30

_MEETING_LANGUAGE = re.compile(r"\b(meet|call|sync|discussion|chat)\b", re.IGNORECASE)
_AMBIGUOUS_PHRASES = re.compile(
    r"\b(maybe|sometime|soon|at some point|let'?s connect)\b", re.IGNORECASE
)
_WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
_DURATION_PATTERN = re.compile(r"\bfor\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", re.IGNORECASE)


class MeetingDetectionResult(BaseModel):
    meeting_detected: bool
    needs_clarification: bool = False
    missing_information: list[str] = []
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    timezone: str | None = None
    description: str | None = None


def _next_weekday(reference: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - reference.weekday()) % 7
    days_ahead = days_ahead or 7
    return reference + timedelta(days=days_ahead)


def _parse_time(body: str) -> time | None:
    match = _TIME_PATTERN.search(body)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return time(hour=hour, minute=minute)


def _parse_duration_minutes(body: str) -> int:
    match = _DURATION_PATTERN.search(body)
    if not match:
        return _DEFAULT_DURATION_MINUTES
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * 60 if unit.startswith("hour") or unit.startswith("hr") else amount


def detect_meeting(email: Email, thread_id: str, tz_name: str, reference_now: datetime) -> MeetingDetectionResult:
    body = email.body
    target_tz = ZoneInfo(tz_name)
    # Weekday/date math ("next Tuesday", "tomorrow") must be relative to the target
    # timezone's local date, not whatever tzinfo reference_now happens to carry (typically
    # UTC for an email timestamp) -- otherwise a meeting near local midnight can resolve to
    # the wrong calendar day, and the stored time would be off by the zone's UTC offset.
    reference_local = reference_now.astimezone(target_tz)

    meeting_language_match = _MEETING_LANGUAGE.search(body)

    if not meeting_language_match:
        # No explicit meeting verb ("meet", "call", ...) at all. A vague
        # scheduling phrase ("maybe", "sometime", "soon", ...) on its own is
        # not enough evidence to attempt day/time extraction -- a day or
        # time appearing elsewhere in an unrelated sentence (e.g. "the
        # Friday 3pm deadline ... I will circle back soon") must not be
        # stitched together into a fabricated meeting. Ask for clarification
        # instead of ever running the day/time parsing logic below.
        if _AMBIGUOUS_PHRASES.search(body):
            return MeetingDetectionResult(
                meeting_detected=False,
                needs_clarification=True,
                missing_information=["specific date", "specific time"],
            )
        return MeetingDetectionResult(meeting_detected=False, needs_clarification=False)

    day_match = _WEEKDAY_PATTERN.search(body)
    tomorrow_match = _TOMORROW_PATTERN.search(body)

    if not day_match and not tomorrow_match:
        return MeetingDetectionResult(
            meeting_detected=False, needs_clarification=True, missing_information=["specific date"]
        )

    parsed_time = _parse_time(body)
    if parsed_time is None:
        return MeetingDetectionResult(
            meeting_detected=False, needs_clarification=True, missing_information=["specific time"]
        )

    if tomorrow_match:
        target_date = (reference_local + timedelta(days=1)).date()
    else:
        weekday = _WEEKDAYS[day_match.group(1).lower()]
        target_date = _next_weekday(reference_local, weekday).date()

    start = datetime.combine(target_date, parsed_time, tzinfo=target_tz)
    duration_minutes = _parse_duration_minutes(body)
    end = start + timedelta(minutes=duration_minutes)

    return MeetingDetectionResult(
        meeting_detected=True,
        needs_clarification=False,
        title=f"Sales Discussion ({email.from_.name or email.from_.email})",
        start=start,
        end=end,
        timezone=tz_name,
        description=f"Sales discussion based on email thread {thread_id}",
    )
