from app.email.models import parse_email
from app.providers.llm.mock import MockLLMProvider


def _email(body: str, subject: str = "Enterprise CRM Proposal"):
    return parse_email(
        {
            "message_id": "msg_001",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": subject,
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_analyze_email_extracts_competitor_and_pain_point():
    provider = MockLLMProvider()
    email = _email("We currently use Salesforce but pricing has become a real pain point for us.")
    result = provider.analyze_email(email)
    assert "Salesforce" in result["competitors"]
    assert any("pric" in p.lower() for p in result["pain_points"])


def test_analyze_email_extracts_seat_requirement():
    provider = MockLLMProvider()
    email = _email("We would need about 100 seats for our sales team.")
    result = provider.analyze_email(email)
    assert any("100" in r for r in result["requirements"])


def test_analyze_email_is_deterministic():
    provider = MockLLMProvider()
    email = _email("We need a demo and a formal pricing proposal.")
    first = provider.analyze_email(email)
    second = provider.analyze_email(email)
    assert first == second


def test_update_context_merges_new_facts_and_tags_provenance():
    provider = MockLLMProvider()
    previous_context = {
        "summary": "",
        "participants": [],
        "company": {},
        "opportunity": {},
        "requirements": [],
        "pain_points": [],
        "products_discussed": [],
        "competitors": [],
        "pricing": {},
        "objections": [],
        "buying_signals": [],
        "decisions": [],
        "commitments": [],
        "open_questions": [],
        "next_actions": [],
        "meetings": [],
    }
    analysis = {
        "email_id": "msg_001",
        "summary": "Customer evaluating CRM",
        "intent": "evaluation",
        "entities": [],
        "facts": [],
        "requirements": ["100 seats"],
        "pain_points": ["Pricing"],
        "buying_signals": ["pricing request"],
        "objections": [],
        "competitors": ["Salesforce"],
        "pricing_mentions": [],
        "commitments": [],
        "action_items": [],
        "meetings": [],
        "people": [],
        "companies": [],
        "products": [],
    }
    new_context = provider.update_context(previous_context, analysis)
    assert new_context["requirements"][0]["value"] == "100 seats"
    assert new_context["requirements"][0]["basis"] == "stated"
    assert new_context["requirements"][0]["source_email_ids"] == ["msg_001"]
    assert any(item["basis"] == "inferred" for item in new_context["buying_signals"] + new_context.get("_inferred", []))


def test_verify_same_fact_uses_similarity():
    # "100 seats" vs "approximately 100 users" never actually reaches Step 4 in the real
    # pipeline: classify_fact_key already maps both to the single "seat_count" fact_key, so
    # they collapse via Step 2's exact match before any fuzzy/LLM comparison happens. Use a
    # pair that genuinely needs and exercises Step 4 instead -- two phrasings of the same
    # non-attribute fact that rapidfuzz's token_sort_ratio scores at 88.46 (verified via
    # rapidfuzz directly), comfortably above the 80 threshold.
    provider = MockLLMProvider()
    assert (
        provider.verify_same_fact(
            "data migration concerns", "concerns about data migration", "ABC Corp", "has_pain_point"
        )
        is True
    )
    assert provider.verify_same_fact("100 seats", "Salesforce integration", "ABC Corp", "requires") is False


def test_draft_reply_produces_subject_and_body():
    provider = MockLLMProvider()
    email = _email("Can you send us pricing for the enterprise plan?")
    context = {"summary": "ABC Corp evaluating enterprise plan", "company": {"name": "ABC Corp"}}
    draft = provider.draft_reply(context, email)
    assert draft["subject"].startswith("Re:")
    assert "ABC Corp" in draft["body"] or "pricing" in draft["body"].lower()


def test_mock_llm_includes_sender_as_mentioned_person():
    provider = MockLLMProvider()
    email = _email("Just checking in.")
    result = provider.analyze_email(email)
    assert result["people_mentioned"] == [
        {"name": "John", "email": "john@example.com", "org": None, "role_hint": None}
    ]


def test_mock_llm_detects_a_mine_commitment_with_weekday_date_phrase():
    provider = MockLLMProvider()
    email = _email("I will send the proposal on Friday.")
    result = provider.analyze_email(email)
    assert len(result["commitments_mentioned"]) == 1
    commitment = result["commitments_mentioned"][0]
    assert commitment["class"] == "mine"
    assert commitment["date_phrase"] == "Friday"


def test_mock_llm_detects_meeting_language_as_meeting_mentioned():
    provider = MockLLMProvider()
    email = _email("Let's meet on Tuesday to go over pricing.")
    result = provider.analyze_email(email)
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "Tuesday"


def test_mock_llm_classification_fields_are_deterministic():
    provider = MockLLMProvider()
    with_signal = provider.analyze_email(_email("Can you send pricing for the enterprise plan?"))
    without_signal = provider.analyze_email(_email("Just an FYI, no action needed."))

    assert with_signal["goal_pillar"] == "Sales"
    assert with_signal["label_applied"] == "Needs reply: ASAP"
    assert without_signal["label_applied"] == "Read only"
    assert with_signal["confidence"] == 0.8


# --- Relative-date meeting/action detection (spec S5.1.1) ---


def test_mock_llm_detects_relative_duration_meeting_with_no_commitment():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Sounds good. We will meet in 2 weeks."))

    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 2 weeks"
    assert result["meetings_mentioned"][0]["is_past"] is False
    # "we will meet" must NOT also be read as a "mine" commitment.
    assert result["commitments_mentioned"] == []


def test_mock_llm_detects_meet_next_weekday():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Let's meet next Friday."))
    assert result["meetings_mentioned"][0]["date_phrase"] == "Friday"


def test_mock_llm_detects_meet_tomorrow():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("We can meet tomorrow."))
    assert result["meetings_mentioned"][0]["date_phrase"] == "tomorrow"


def test_mock_llm_detects_meeting_noun_form_with_digit_duration():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("The meeting is in 10 days."))
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 10 days"


def test_mock_llm_detects_catch_up_phrase_as_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Let's catch up in 10 days."))
    assert len(result["meetings_mentioned"]) == 1


def test_mock_llm_detects_both_a_commitment_and_a_relative_date_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(
        _email("I will send the proposal. We can meet in 2 weeks to go over it.")
    )
    assert len(result["commitments_mentioned"]) == 1
    assert result["commitments_mentioned"][0]["class"] == "mine"
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 2 weeks"


def test_mock_llm_does_not_detect_historical_meeting_mention_as_a_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("We met last week and it went well."))
    # "met" (past tense) is a different word from the "meet" trigger -- this is
    # intentionally never recognized as a meeting mention at all by the keyword-based mock.
    assert result["meetings_mentioned"] == []
