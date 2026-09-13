import random
from datetime import datetime, timedelta, timezone
from typing import Any

_CUSTOMER = {"name": "John Smith", "email": "john.smith@abccorp-demo.example"}
_SALES_REP = {"name": "Ashok Kumar", "email": "ashok@oursalesagent-demo.example"}
_THREAD_SUBJECT = "Enterprise CRM Proposal"


def _base_timestamp(seed: int) -> datetime:
    rng = random.Random(seed)
    day_offset = rng.randint(0, 3)
    return datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc) + timedelta(days=day_offset)


def _email(
    index: int,
    message_id: str,
    thread_id: str,
    subject: str,
    body: str,
    timestamp: datetime,
    in_reply_to: str | None,
    references: list[str],
    from_customer: bool,
) -> dict[str, Any]:
    sender = _CUSTOMER if from_customer else _SALES_REP
    recipient = _SALES_REP if from_customer else _CUSTOMER
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "from": sender,
        "to": [recipient],
        "cc": [],
        "subject": subject,
        "body": body,
        "timestamp": timestamp.isoformat(),
        "in_reply_to": in_reply_to,
        "references": references,
        "attachments": [],
        "labels": [],
    }


def generate_demo_emails(seed: int) -> list[dict[str, Any]]:
    start = _base_timestamp(seed)
    thread_id = "thread_demo_001"
    message_ids: list[str] = []
    emails: list[dict[str, Any]] = []

    bodies = [
        (
            True,
            "Enterprise CRM Proposal",
            "Hi, we're a mid-market logistics company evaluating enterprise CRM options for our "
            "sales team. Could you share more about your enterprise plan?",
        ),
        (
            False,
            "Re: Enterprise CRM Proposal",
            "Thanks for reaching out! Happy to walk you through the enterprise plan. Could you tell "
            "me a bit about what's not working well with your current process?",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Our biggest pain point right now is pricing visibility and a lot of manual data entry "
            "across spreadsheets. We currently use Salesforce but it's become expensive and clunky "
            "for our team's workflow.",
        ),
        (
            False,
            "Re: Enterprise CRM Proposal",
            "That's very common feedback about Salesforce at your scale. Our enterprise plan "
            "includes automated data sync and transparent per-seat pricing. Would a demo help?",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "A demo would be great. Let's meet Tuesday at 3 PM for 30 minutes to go over the "
            "enterprise pricing and see the product in action.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Quick update before our call: after reviewing with the team, we'd need about 100 seats "
            "to start, covering our full sales and account management org.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "One more thing — our VP of Sales, Sarah, will also be joining future conversations as "
            "the final decision maker on this purchase.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Following the reorg we announced, we now expect closer to 150 seats rather than 100, "
            "since two additional regional teams are moving onto the new CRM.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Could you send over a formal proposal and pricing for 150 seats so we can review it "
            "with procurement before the end of the month?",
        ),
    ]

    for index, (from_customer, subject, body) in enumerate(bodies):
        message_id = f"msg_{index + 1:03d}"
        timestamp = start + timedelta(days=index, hours=index)
        in_reply_to = message_ids[-1] if message_ids else None
        references = list(message_ids)
        emails.append(
            _email(
                index=index,
                message_id=message_id,
                thread_id=thread_id,
                subject=subject,
                body=body,
                timestamp=timestamp,
                in_reply_to=in_reply_to,
                references=references,
                from_customer=from_customer,
            )
        )
        message_ids.append(message_id)

    return emails
