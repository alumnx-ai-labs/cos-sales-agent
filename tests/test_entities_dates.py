from datetime import datetime, timedelta, timezone

from app.entities.dates import find_date_phrase, resolve_date_phrase

_NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)  # a Sunday


def test_resolve_date_phrase_returns_none_for_no_phrase():
    assert resolve_date_phrase(None, _NOW) == (None, None)
    assert resolve_date_phrase("", _NOW) == (None, None)


def test_resolve_date_phrase_handles_explicit_month_day_as_stated():
    resolved, date_type = resolve_date_phrase("by June 5th", _NOW)
    assert date_type == "stated"
    assert resolved.month == 6
    assert resolved.day == 5
    assert resolved.year == 2027  # June 5 already passed in the reference year, rolls to next year


def test_resolve_date_phrase_explicit_date_on_the_same_day_does_not_roll_to_next_year():
    # A same-day reference ("June 5th" sent on June 5th at 2pm) must resolve to THIS
    # year's June 5th, not next year's -- comparing full timestamps (candidate normalized
    # to midnight vs. reference_now's real time-of-day) would wrongly treat today as
    # "already passed" and roll forward a year.
    reference = datetime(2026, 6, 5, 14, 0, tzinfo=timezone.utc)
    resolved, date_type = resolve_date_phrase("by June 5th", reference)
    assert date_type == "stated"
    assert resolved.year == 2026
    assert resolved.month == 6
    assert resolved.day == 5


def test_resolve_date_phrase_handles_tomorrow_as_inferred():
    resolved, date_type = resolve_date_phrase("let's talk tomorrow", _NOW)
    assert date_type == "inferred"
    assert resolved.date() == (_NOW.date().replace(day=_NOW.day + 1))


def test_resolve_date_phrase_handles_weekday_as_inferred():
    resolved, date_type = resolve_date_phrase("can we sync next Friday", _NOW)
    assert date_type == "inferred"
    assert resolved.weekday() == 4  # Friday


def test_resolve_date_phrase_handles_vague_phrase_as_window():
    resolved, date_type = resolve_date_phrase("sometime end of month", _NOW)
    assert resolved is None
    assert date_type == "window"


def test_resolve_date_phrase_falls_back_to_window_for_unrecognized_phrase():
    resolved, date_type = resolve_date_phrase("whenever works", _NOW)
    assert resolved is None
    assert date_type == "window"


def test_resolve_date_phrase_handles_relative_duration_in_weeks_as_inferred():
    # Spec worked example: email dated 2026-09-17, "in 2 weeks" -> 2026-10-01
    reference = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    resolved, date_type = resolve_date_phrase("We will meet in 2 weeks.", reference)
    assert date_type == "inferred"
    assert resolved.date().isoformat() == "2026-10-01"


def test_resolve_date_phrase_handles_relative_duration_in_days_with_digit():
    resolved, date_type = resolve_date_phrase("The meeting is in 10 days.", _NOW)
    assert date_type == "inferred"
    assert resolved == _NOW + timedelta(days=10)


def test_resolve_date_phrase_handles_relative_duration_with_spelled_out_number():
    resolved, date_type = resolve_date_phrase("Let's catch up in two weeks.", _NOW)
    assert date_type == "inferred"
    assert resolved == _NOW + timedelta(days=14)


def test_resolve_date_phrase_recognizes_next_month_explicitly_as_window():
    resolved, date_type = resolve_date_phrase("We should meet sometime next month.", _NOW)
    assert resolved is None
    assert date_type == "window"


def test_find_date_phrase_returns_first_recognized_expression():
    # The weekday pattern matches only the weekday word itself, not a preceding "next" --
    # resolve_date_phrase always computes the *next* occurrence of that weekday regardless,
    # so the "next" prefix carries no additional information it needs.
    assert find_date_phrase("We will meet in 2 weeks.") == "in 2 weeks"
    assert find_date_phrase("Let's meet next Friday.") == "Friday"
    assert find_date_phrase("We can meet tomorrow.") == "tomorrow"
    assert find_date_phrase("The meeting is in 10 days.") == "in 10 days"


def test_find_date_phrase_returns_none_when_nothing_recognized():
    assert find_date_phrase("Just checking in, no dates mentioned.") is None
