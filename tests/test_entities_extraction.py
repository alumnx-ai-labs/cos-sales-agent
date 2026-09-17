from app.email.models import parse_email
from app.entities.extraction import domains_from_emails, envelope_people, extract_email_addresses_from_text


def test_extract_email_addresses_from_text_finds_all_and_dedupes_case_insensitively():
    text = "Reach me at Jane@Example.com or jane@example.com, cc bob@other.io."
    assert extract_email_addresses_from_text(text) == ["bob@other.io", "jane@example.com"]


def test_extract_email_addresses_from_text_returns_empty_when_none_present():
    assert extract_email_addresses_from_text("No addresses here.") == []


def test_domains_from_emails():
    assert domains_from_emails(["jane@example.com", "bob@other.io", "jane2@example.com"]) == [
        "example.com",
        "other.io",
    ]


def test_envelope_people_dedupes_by_email_across_from_to_cc():
    email = parse_email(
        {
            "message_id": "msg_001",
            "from": {"name": "Jane", "email": "jane@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "cc": [{"name": "Jane Duplicate", "email": "Jane@Example.com"}],
            "subject": "Hi",
            "body": "Body",
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )

    people = envelope_people(email)

    assert len(people) == 2
    emails = sorted(p.email for p in people)
    assert emails == ["ashok@example.com", "jane@example.com"]
