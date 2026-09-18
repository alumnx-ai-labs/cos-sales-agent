import json
import re
from typing import Any

import anthropic

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider

_ANALYSIS_INSTRUCTIONS = (
    "You are a sales email analyst. Given the email below, return ONLY a JSON object with keys: "
    "summary, intent, entities, facts (list of {subject,predicate,object}), requirements, pain_points, "
    "buying_signals, objections, competitors, pricing_mentions, commitments, action_items, "
    "meetings (list of short plain strings, e.g. 'Call last Tuesday' -- NOT objects; use "
    "meetings_mentioned below for structured detail on the same meetings), "
    "people, companies, products (each a list of short plain strings, not objects), "
    "people_mentioned (list of {name, email, org, role_hint} for each person mentioned or corresponding), "
    "projects_mentioned (list of {name, org, objective_hint}), "
    "commitments_mentioned (list of {what, class: one of mine/owed_to_me/theirs/recap, owed_by, owed_to, "
    "date_phrase (the raw text phrase describing when, e.g. 'next Friday' -- never a resolved date), "
    "importance_hint}), "
    "meetings_mentioned (list of {date_phrase, attendees, is_past, actions_raised}), "
    "personal_items_mentioned (list of {item_type, description, date_phrase}), "
    "goal_pillar (a short label for which business goal this relates to, e.g. 'Sales'), "
    "label_applied (exactly one of: 'Needs reply: ASAP', 'Needs reply: Soon', 'Read only', 'Delete', "
    "'Undecided'), confidence (0.0-1.0). "
    "Do not invent or assign any canonical entity ID yourself; only describe what you observe in the email. "
    "Entity ID assignment is handled separately by the system. "
    "Use empty lists/strings for anything not present. No prose, JSON only."
)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _complete_json(self, system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        text = _CODE_FENCE_RE.sub("", text).strip()
        return json.loads(text)

    def analyze_email(self, email: Email) -> dict[str, Any]:
        result = self._complete_json(
            _ANALYSIS_INSTRUCTIONS,
            f"Subject: {email.subject}\n\nBody:\n{email.body}",
            max_tokens=4096,
        )
        result.setdefault("email_id", email.message_id)
        return result

    def update_context(self, previous_context: dict[str, Any], new_analysis: dict[str, Any]) -> dict[str, Any]:
        instructions = (
            "Merge the new email analysis into the previous structured sales context. Return ONLY the "
            "updated context JSON with the same shape as the previous context. Every list item must be an "
            "object with value/basis/source_email_ids; basis is 'stated' for customer-stated facts and "
            "'inferred' for your own inferences. Never remove prior information unless clearly superseded."
        )
        user = json.dumps({"previous_context": previous_context, "new_analysis": new_analysis})
        return self._complete_json(instructions, user, max_tokens=4096)

    def verify_same_fact(self, existing_value: str, new_value: str, subject: str, predicate: str) -> bool:
        instructions = "Answer ONLY with JSON: {\"same_fact\": true} or {\"same_fact\": false}."
        user = (
            f"Subject: {subject}\nPredicate: {predicate}\nExisting value: {existing_value}\n"
            f"New value: {new_value}\nAre these describing the same underlying fact?"
        )
        result = self._complete_json(instructions, user)
        return bool(result.get("same_fact", False))

    def draft_reply(self, context: dict[str, Any], latest_email: Email) -> dict[str, Any]:
        instructions = "Draft a professional sales reply. Return ONLY JSON: {\"subject\": ..., \"body\": ...}."
        user = json.dumps(
            {
                "context": context,
                "latest_email_subject": latest_email.subject,
                "latest_email_body": latest_email.body,
                "sender_name": latest_email.from_.name or latest_email.from_.email,
            }
        )
        return self._complete_json(instructions, user, max_tokens=2048)
