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
