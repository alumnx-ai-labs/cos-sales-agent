import re

from app.email.models import Email, EmailAddress

_REPLY_FORWARD_PREFIX = re.compile(r"^\s*(re|fwd|fw)\s*:\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def normalize_subject(subject: str) -> str:
    text = subject.strip()
    while True:
        stripped = _REPLY_FORWARD_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    return _WHITESPACE.sub(" ", text).strip()


def _normalize_address(address: EmailAddress) -> EmailAddress:
    return EmailAddress(name=address.name, email=address.email.lower())


def normalize_email(email: Email) -> Email:
    return email.model_copy(
        update={
            "subject": normalize_subject(email.subject),
            "body": _WHITESPACE.sub(" ", email.body.strip()),
            "from_": _normalize_address(email.from_),
            "to": [_normalize_address(a) for a in email.to],
            "cc": [_normalize_address(a) for a in email.cc],
        }
    )
