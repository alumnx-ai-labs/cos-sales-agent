from datetime import datetime, timedelta

from pydantic import BaseModel

from app.email.models import Email
from app.email.normalizer import normalize_subject


class ThreadCandidate(BaseModel):
    thread_id: str
    normalized_subject: str
    participant_emails: set[str]
    message_ids: set[str]
    last_message_at: datetime


def _participants(email: Email) -> set[str]:
    return {email.from_.email, *(a.email for a in email.to), *(a.email for a in email.cc)}


def resolve_thread_id(
    email: Email,
    candidates: list[ThreadCandidate],
    window_days: int = 14,
) -> str:
    if email.thread_id:
        return email.thread_id

    if email.in_reply_to:
        for candidate in candidates:
            if email.in_reply_to in candidate.message_ids:
                return candidate.thread_id

    if email.references:
        for candidate in candidates:
            if candidate.message_ids.intersection(email.references):
                return candidate.thread_id

    normalized = normalize_subject(email.subject)
    participants = _participants(email)

    for candidate in candidates:
        if candidate.normalized_subject == normalized and candidate.participant_emails.intersection(participants):
            return candidate.thread_id

    window = timedelta(days=window_days)
    matching = [
        c
        for c in candidates
        if c.participant_emails.intersection(participants)
        and email.timestamp - c.last_message_at <= window
    ]
    if matching:
        matching.sort(key=lambda c: c.last_message_at, reverse=True)
        return matching[0].thread_id

    return f"thread_{email.message_id}"
