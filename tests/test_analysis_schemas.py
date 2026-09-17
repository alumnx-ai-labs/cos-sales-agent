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


def test_email_analysis_entity_signal_defaults():
    analysis = EmailAnalysis(email_id="msg_001", summary="s", intent="evaluation")
    assert analysis.people_mentioned == []
    assert analysis.projects_mentioned == []
    assert analysis.commitments_mentioned == []
    assert analysis.meetings_mentioned == []
    assert analysis.personal_items_mentioned == []
    assert analysis.goal_pillar == ""
    assert analysis.label_applied == "Undecided"
    assert analysis.confidence == 0.0


def test_email_analysis_accepts_raw_commitment_with_class_alias():
    analysis = EmailAnalysis.model_validate(
        {
            "email_id": "msg_001",
            "summary": "s",
            "intent": "evaluation",
            "commitments_mentioned": [
                {"what": "send case study", "class": "mine", "date_phrase": "next Friday"}
            ],
        }
    )
    assert analysis.commitments_mentioned[0].commitment_class == "mine"
