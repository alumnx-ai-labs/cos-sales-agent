from typing import Any

from app.interfaces.email_provider import EmailProvider


class MockEmailProvider(EmailProvider):
    def __init__(self, payloads: list[dict[str, Any]]):
        self._payloads = payloads

    def fetch_emails(self, limit: int) -> list[dict[str, Any]]:
        return self._payloads[:limit]

    def send_email(self, to: str, subject: str, body: str) -> None:
        print("[SIMULATED EMAIL SEND]")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print()
        print(body)
