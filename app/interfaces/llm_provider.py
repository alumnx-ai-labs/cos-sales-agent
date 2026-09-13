from abc import ABC, abstractmethod
from typing import Any

from app.email.models import Email


class LLMProvider(ABC):
    @abstractmethod
    def analyze_email(self, email: Email) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_context(self, previous_context: dict[str, Any], new_analysis: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def verify_same_fact(self, existing_value: str, new_value: str, subject: str, predicate: str) -> bool:
        ...

    @abstractmethod
    def draft_reply(self, context: dict[str, Any], latest_email: Email) -> dict[str, Any]:
        ...
