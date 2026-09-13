from app.analysis.schemas import EmailAnalysis
from app.context.engine import build_next_context
from app.context.models import ThreadContext
from app.providers.llm.mock import MockLLMProvider


def test_build_first_context_version_from_empty_previous():
    llm = MockLLMProvider()
    analysis = EmailAnalysis(
        email_id="msg_001",
        summary="ABC Corp evaluating CRM",
        intent="evaluation",
        requirements=["100 seats"],
        competitors=["Salesforce"],
    )
    context, changes = build_next_context(previous=None, analysis=analysis, source_email_id="msg_001", llm=llm)

    assert context.requirements[0].value == "100 seats"
    assert context.requirements[0].source_email_ids == ["msg_001"]
    assert any(c.type == "ADDED" and c.field == "requirements" for c in changes)


def test_build_second_context_version_accumulates_on_first():
    llm = MockLLMProvider()
    analysis_1 = EmailAnalysis(email_id="msg_001", summary="Intro", intent="evaluation", requirements=["100 seats"])
    context_v1, _ = build_next_context(previous=None, analysis=analysis_1, source_email_id="msg_001", llm=llm)

    analysis_2 = EmailAnalysis(
        email_id="msg_007", summary="Follow up", intent="evaluation", requirements=["150 seats"]
    )
    context_v2, changes = build_next_context(
        previous=context_v1, analysis=analysis_2, source_email_id="msg_007", llm=llm
    )

    values = {r.value for r in context_v2.requirements}
    assert "100 seats" in values
    assert "150 seats" in values
    assert any(c.type == "ADDED" and c.detail == "150 seats" for c in changes)


def test_context_never_loses_prior_information_when_new_analysis_is_empty():
    llm = MockLLMProvider()
    analysis_1 = EmailAnalysis(email_id="msg_001", summary="Intro", intent="evaluation", competitors=["Salesforce"])
    context_v1, _ = build_next_context(previous=None, analysis=analysis_1, source_email_id="msg_001", llm=llm)

    analysis_2 = EmailAnalysis(email_id="msg_002", summary="Just checking in", intent="evaluation")
    context_v2, _ = build_next_context(previous=context_v1, analysis=analysis_2, source_email_id="msg_002", llm=llm)

    assert "Salesforce" in {c.value for c in context_v2.competitors}
