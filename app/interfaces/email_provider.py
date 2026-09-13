from abc import ABC, abstractmethod
from typing import Any


class EmailProvider(ABC):
    @abstractmethod
    def fetch_emails(self, limit: int) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def send_email(self, to: str, subject: str, body: str) -> None:
        ...
