from app.analysis.schemas import EmailAnalysis, Fact


def test_email_analysis_defaults():
    analysis = EmailAnalysis(email_id="msg_001", summary="s", intent="evaluation")
    assert analysis.facts == []
    assert analysis.pain_points == []
    assert analysis.competitors == []


def test_email_analysis_accepts_facts():
    analysis = EmailAnalysis(
        email_id="msg_001",
        summary="s",
        intent="evaluation",
        facts=[Fact(subject="Customer", predicate="uses", object="Salesforce")],
    )
    assert analysis.facts[0].object == "Salesforce"
