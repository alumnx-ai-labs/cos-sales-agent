import re

from app.email.models import Email, EmailAddress

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_email_addresses_from_text(text: str) -> list[str]:
    return sorted({match.lower() for match in _EMAIL_PATTERN.findall(text)})


def domains_from_emails(emails: list[str]) -> list[str]:
    return sorted({e.split("@", 1)[1] for e in emails if "@" in e})


def envelope_people(email: Email) -> list[EmailAddress]:
    seen: dict[str, EmailAddress] = {}
    for address in [email.from_, *email.to, *email.cc]:
        seen.setdefault(address.email.lower(), address)
    return list(seen.values())
