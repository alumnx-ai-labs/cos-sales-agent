from app.analysis.schemas import EmailAnalysis
from app.context.models import ThreadContext
from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider
from app.replies.models import ReplyDraftContent


def needs_reply(analysis: EmailAnalysis, email: Email) -> bool:
    has_signal = any(
        [
            analysis.buying_signals,
            analysis.requirements,
            analysis.pain_points,
            analysis.objections,
            analysis.pricing_mentions,
            analysis.action_items,
        ]
    )
    has_question = "?" in email.body
    return has_signal or has_question


def draft_reply(llm: LLMProvider, context: ThreadContext, email: Email) -> ReplyDraftContent:
    raw = llm.draft_reply(context.model_dump(), email)
    return ReplyDraftContent.model_validate(raw)
