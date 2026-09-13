from app.analysis.schemas import EmailAnalysis
from app.context.diff import diff_context
from app.context.models import ContextChange, ThreadContext
from app.interfaces.llm_provider import LLMProvider


def build_next_context(
    previous: ThreadContext | None,
    analysis: EmailAnalysis,
    source_email_id: str,
    llm: LLMProvider,
) -> tuple[ThreadContext, list[ContextChange]]:
    previous_context = previous or ThreadContext()

    raw_next = llm.update_context(previous_context.model_dump(), analysis.model_dump())
    next_context = ThreadContext.model_validate(raw_next)

    changes = diff_context(previous_context, next_context, source_email_id=source_email_id)
    return next_context, changes
