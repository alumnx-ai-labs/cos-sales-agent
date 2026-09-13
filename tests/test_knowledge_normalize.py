from app.knowledge.normalize import (
    classify_fact_key,
    extract_leading_number,
    normalize_text,
    slugify,
)


def test_normalize_text_lowercases_and_strips_punctuation():
    assert normalize_text("  100 Seats!! ") == "100 seats"


def test_normalize_text_converts_number_words():
    assert normalize_text("one hundred seats") == "100 seats"


def test_slugify_produces_snake_case_key():
    assert slugify("ABC Corp") == "abc_corp"
    assert slugify("Ashok's Team, Inc.") == "ashoks_team_inc"


def test_classify_fact_key_for_seat_count():
    assert classify_fact_key("requires", "100 seats") == "seat_count"
    assert classify_fact_key("requires", "approximately 100 users") == "seat_count"
    assert classify_fact_key("requires", "150 licenses") == "seat_count"


def test_classify_fact_key_for_budget_and_close_date():
    assert classify_fact_key("has", "a budget of $75K") == "budget"
    assert classify_fact_key("targets", "close date of Nov 1") == "close_date"


def test_classify_fact_key_falls_back_to_normalized_object_for_set_membership():
    assert classify_fact_key("mentioned_competitor", "Salesforce") == "salesforce"
    assert classify_fact_key("mentioned_competitor", "HubSpot") == "hubspot"


def test_extract_leading_number_parses_digits_from_normalized_text():
    assert extract_leading_number("150 seats") == 150
    assert extract_leading_number(normalize_text("one hundred seats")) == 100
    assert extract_leading_number("Salesforce") is None
