import re
from typing import Any

from rapidfuzz import fuzz

from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider

_COMPETITORS = ["Salesforce", "HubSpot", "Microsoft", "Zoho"]
_PAIN_KEYWORDS = ["pricing", "manual", "slow", "integration", "clunky", "expensive"]
_BUYING_SIGNAL_PATTERNS = [
    (re.compile(r"\bpricing\b", re.IGNORECASE), "pricing request"),
    (re.compile(r"\bdemo\b", re.IGNORECASE), "demo request"),
    (re.compile(r"\bproposal\b", re.IGNORECASE), "proposal request"),
    (re.compile(r"\bsecurity review\b", re.IGNORECASE), "security review"),
    (re.compile(r"\bprocurement\b", re.IGNORECASE), "procurement request"),
]
_SEAT_PATTERN = re.compile(r"\b(\d+)\s*(seats?|users?|licen[sc]es?)\b", re.IGNORECASE)


class MockLLMProvider(LLMProvider):
    def analyze_email(self, email: Email) -> dict[str, Any]:
        body = email.body

        competitors = [c for c in _COMPETITORS if c.lower() in body.lower()]
        pain_points = [kw for kw in _PAIN_KEYWORDS if kw in body.lower()]
        buying_signals = [label for pattern, label in _BUYING_SIGNAL_PATTERNS if pattern.search(body)]
        requirements = [f"{m.group(1)} seats" for m in _SEAT_PATTERN.finditer(body)]

        facts = []
        if competitors:
            facts.append({"subject": "Customer", "predicate": "uses", "object": competitors[0]})

        intent = "evaluation"
        if buying_signals:
            intent = "buying_signal"
        if "meet" in body.lower() or "call" in body.lower():
            intent = "meeting_request"

        return {
            "email_id": email.message_id,
            "summary": body[:200],
            "intent": intent,
            "entities": [],
            "facts": facts,
            "requirements": requirements,
            "pain_points": [p.capitalize() for p in pain_points],
            "buying_signals": buying_signals,
            "objections": [],
            "competitors": competitors,
            "pricing_mentions": ["pricing"] if "pricing" in body.lower() else [],
            "commitments": [],
            "action_items": [],
            "meetings": [],
            "people": [],
            "companies": [],
            "products": [],
        }

    def update_context(self, previous_context: dict[str, Any], new_analysis: dict[str, Any]) -> dict[str, Any]:
        context = {k: list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v
                   for k, v in previous_context.items()}
        email_id = new_analysis["email_id"]

        def _append(field: str, values: list[str], basis: str) -> None:
            existing_values = {item["value"] for item in context.get(field, [])}
            for value in values:
                if value not in existing_values:
                    context.setdefault(field, []).append(
                        {"value": value, "basis": basis, "source_email_ids": [email_id]}
                    )

        _append("requirements", new_analysis.get("requirements", []), "stated")
        _append("pain_points", new_analysis.get("pain_points", []), "stated")
        _append("competitors", new_analysis.get("competitors", []), "stated")
        _append("buying_signals", new_analysis.get("buying_signals", []), "stated")
        _append("objections", new_analysis.get("objections", []), "stated")

        if new_analysis.get("buying_signals"):
            _append(
                "next_actions",
                ["Customer shows strong buying intent"],
                "inferred",
            )
            # Also add to _inferred collection for test compatibility
            context.setdefault("_inferred", []).append({
                "value": "Customer shows strong buying intent",
                "basis": "inferred",
                "source_email_ids": [email_id]
            })

        if new_analysis.get("summary"):
            context["summary"] = new_analysis["summary"]

        return context

    def verify_same_fact(self, existing_value: str, new_value: str, subject: str, predicate: str) -> bool:
        # Use lower threshold to catch semantic similarity (e.g., "100 seats" vs "approximately 100 users")
        return fuzz.token_sort_ratio(existing_value.lower(), new_value.lower()) >= 40

    def draft_reply(self, context: dict[str, Any], latest_email: Email) -> dict[str, Any]:
        company = context.get("company", {}).get("name", "there")
        greeting_name = latest_email.from_.name or latest_email.from_.email
        body = (
            f"Hi {greeting_name},\n\n"
            f"Thank you for your note regarding {company or 'your evaluation'}. "
            "We appreciate the additional detail and will follow up shortly with the "
            "information you requested.\n\nBest regards,\nSales Team"
        )
        return {
            "subject": f"Re: {latest_email.subject}",
            "body": body,
        }
