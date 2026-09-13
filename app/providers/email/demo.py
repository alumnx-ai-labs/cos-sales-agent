from typing import Any

from demo_data.generator import generate_demo_emails

from app.interfaces.email_provider import EmailProvider


class DemoEmailProvider(EmailProvider):
    def __init__(self, seed: int):
        self._emails = generate_demo_emails(seed=seed)

    def fetch_emails(self, limit: int) -> list[dict[str, Any]]:
        return self._emails[:limit]

    def send_email(self, to: str, subject: str, body: str) -> None:
        print("[SIMULATED EMAIL SEND]")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print()
        print(body)
