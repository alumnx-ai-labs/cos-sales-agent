from app.email.models import parse_email
from app.email.normalizer import normalize_email, normalize_subject


def _base_raw(**overrides):
    raw = {
        "message_id": "msg_001",
        "from": {"name": "John Smith", "email": "JOHN@Example.com"},
        "to": [{"name": "Ashok", "email": "Ashok@Example.com"}],
        "subject": "  Re: Re: Enterprise CRM Proposal  ",
        "body": "  We are evaluating your enterprise plan...  ",
        "timestamp": "2026-09-13T10:30:00Z",
    }
    raw.update(overrides)
    return raw


def test_normalize_subject_strips_reply_forward_prefixes():
    assert normalize_subject("Re: Re: Fwd: Enterprise Deal") == "Enterprise Deal"
    assert normalize_subject("  FW:  Pricing   Question  ") == "Pricing Question"


def test_normalize_email_trims_and_lowercases_addresses():
    email = parse_email(_base_raw())
    normalized = normalize_email(email)
    assert normalized.subject == "Enterprise CRM Proposal"
    assert normalized.body == "We are evaluating your enterprise plan..."
    assert normalized.from_.email == "john@example.com"
    assert normalized.to[0].email == "ashok@example.com"
    # original is untouched (immutable transform)
    assert email.from_.email == "JOHN@Example.com"
