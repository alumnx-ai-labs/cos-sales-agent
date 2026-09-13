from app.analysis.schemas import EmailAnalysis
from app.context.models import ThreadContext
from app.email.models import parse_email
from app.replies.drafter import draft_reply, needs_reply
from app.providers.llm.mock import MockLLMProvider


def _email(body="Can you send pricing information?"):
    return parse_email(
        {
            "message_id": "msg_004",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": "Enterprise pricing",
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_needs_reply_true_when_buying_signals_present():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation", buying_signals=["pricing request"])
    assert needs_reply(analysis, _email()) is True


def test_needs_reply_false_when_no_signals_and_no_question():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation")
    email = _email(body="Thanks, sounds good.")
    assert needs_reply(analysis, email) is False


def test_needs_reply_true_when_body_contains_question():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation")
    email = _email(body="Can we schedule a call?")
    assert needs_reply(analysis, email) is True


def test_draft_reply_returns_subject_and_body():
    llm = MockLLMProvider()
    context = ThreadContext(summary="ABC Corp evaluating enterprise plan")
    draft = draft_reply(llm, context, _email())
    assert draft.subject == "Re: Enterprise pricing"
    assert len(draft.body) > 0
