import pytest
from pydantic import ValidationError

from app.email.models import Email, parse_email


VALID_RAW = {
    "message_id": "msg_001",
    "thread_id": "thread_001",
    "from": {"name": "John Smith", "email": "john@example.com"},
    "to": [{"name": "Ashok", "email": "ashok@example.com"}],
    "cc": [],
    "subject": "Enterprise CRM Proposal",
    "body": "We are evaluating your enterprise plan...",
    "timestamp": "2026-09-13T10:30:00Z",
    "in_reply_to": None,
    "references": [],
    "attachments": [],
    "labels": [],
}


def test_parse_valid_email():
    email = parse_email(VALID_RAW)
    assert isinstance(email, Email)
    assert email.message_id == "msg_001"
    assert email.from_.email == "john@example.com"
    assert email.to[0].email == "ashok@example.com"


def test_parse_email_missing_required_field_raises():
    raw = dict(VALID_RAW)
    del raw["message_id"]
    with pytest.raises(ValidationError):
        parse_email(raw)


def test_parse_email_invalid_sender_raises():
    raw = dict(VALID_RAW)
    raw["from"] = {"name": "John", "email": "not-an-email"}
    with pytest.raises(ValidationError):
        parse_email(raw)


def test_parse_email_defaults_optional_fields():
    raw = {
        "message_id": "msg_002",
        "from": {"name": "A", "email": "a@example.com"},
        "to": [{"name": "B", "email": "b@example.com"}],
        "subject": "Hi",
        "body": "Body",
        "timestamp": "2026-09-13T10:30:00Z",
    }
    email = parse_email(raw)
    assert email.thread_id is None
    assert email.cc == []
    assert email.references == []
    assert email.attachments == []
    assert email.labels == []
