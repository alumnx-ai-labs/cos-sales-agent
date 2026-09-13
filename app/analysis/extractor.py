from pydantic import BaseModel, ValidationError

from app.analysis.schemas import EmailAnalysis
from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider


class AnalysisOutcome(BaseModel):
    success: bool
    analysis: EmailAnalysis | None = None
    error: str | None = None


def analyze_email_with_validation(
    llm: LLMProvider, email: Email, max_retries: int = 1
) -> AnalysisOutcome:
    last_error: str | None = None
    attempts = max_retries + 1

    for _ in range(attempts):
        raw = llm.analyze_email(email)
        raw.setdefault("email_id", email.message_id)
        try:
            analysis = EmailAnalysis.model_validate(raw)
            return AnalysisOutcome(success=True, analysis=analysis, error=None)
        except ValidationError as exc:
            last_error = str(exc)

    return AnalysisOutcome(success=False, analysis=None, error=last_error)
