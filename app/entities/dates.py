import re
from datetime import datetime, timedelta

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_EXPLICIT_DATE_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RELATIVE_DURATION_PATTERN = re.compile(
    r"\bin\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+(day|days|week|weeks)\b",
    re.IGNORECASE,
)
_VAGUE_WINDOW_PATTERN = re.compile(
    r"\bnext month\b|\bsometime\b|\bend of (?:the )?month\b", re.IGNORECASE
)
_DATE_PHRASE_PATTERNS = [
    _EXPLICIT_DATE_PATTERN,
    _TOMORROW_PATTERN,
    _WEEKDAY_PATTERN,
    _RELATIVE_DURATION_PATTERN,
    _VAGUE_WINDOW_PATTERN,
]


def _next_weekday(reference: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - reference.weekday()) % 7
    days_ahead = days_ahead or 7
    return reference + timedelta(days=days_ahead)


def find_date_phrase(text: str) -> str | None:
    """Return the first recognized date-related substring in text, verbatim, or None.

    Used by MockLLMProvider so the phrase a mention carries and the phrase
    resolve_date_phrase later resolves come from the same pattern set (spec S5.1.1).
    """
    for pattern in _DATE_PHRASE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def resolve_date_phrase(
    phrase: str | None, reference_now: datetime
) -> tuple[datetime | None, str | None]:
    if not phrase:
        return None, None

    explicit_match = _EXPLICIT_DATE_PATTERN.search(phrase)
    if explicit_match:
        month = _MONTHS[explicit_match.group(1).lower()[:3]]
        day = int(explicit_match.group(2))
        year = reference_now.year
        try:
            candidate = reference_now.replace(
                year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
            )
            # Compare dates, not full timestamps: an email sent on June 5th referencing
            # "June 5th" means today, not next year. Comparing candidate < reference_now
            # (full precision) would incorrectly roll same-day references forward a year,
            # since candidate is normalized to midnight and reference_now carries a real
            # time-of-day that is almost always later than midnight.
            if candidate.date() < reference_now.date():
                candidate = candidate.replace(year=year + 1)
        except ValueError:
            # day is not valid for month/year (e.g. "June 45th", "Feb 30") -- a date was
            # clearly mentioned but can't be pinned to a specific day, so fall back to the
            # same "window" semantic used for other unresolvable-but-present date phrases.
            return None, "window"
        return candidate, "stated"

    if _TOMORROW_PATTERN.search(phrase):
        return reference_now + timedelta(days=1), "inferred"

    weekday_match = _WEEKDAY_PATTERN.search(phrase)
    if weekday_match:
        weekday = _WEEKDAYS[weekday_match.group(1).lower()]
        return _next_weekday(reference_now, weekday), "inferred"

    duration_match = _RELATIVE_DURATION_PATTERN.search(phrase)
    if duration_match:
        amount_word = duration_match.group(1).lower()
        amount = int(amount_word) if amount_word.isdigit() else _NUMBER_WORDS[amount_word]
        unit = duration_match.group(2).lower()
        days = amount * 7 if unit.startswith("week") else amount
        return reference_now + timedelta(days=days), "inferred"

    return None, "window"
