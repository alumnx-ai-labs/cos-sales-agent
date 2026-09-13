from typing import Any

from app.interfaces.email_provider import EmailProvider


class MCPEmailProvider(EmailProvider):
    """Adapter around an MCP email server connection.

    A concrete MCP client is injected by whoever wires up MCP_EMAIL_ENABLED=true
    for their own mailbox; this class intentionally does not assume any specific
    mail server. Until a client is supplied, calling it raises rather than
    silently falling back to demo/mock behavior.
    """

    def __init__(self, client: Any = None):
        self._client = client

    def fetch_emails(self, limit: int) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError(
                "MCP email provider is not configured — set MCP_EMAIL_ENABLED=true and "
                "provide a server connection"
            )
        return self._client.fetch_emails(limit=limit)

    def send_email(self, to: str, subject: str, body: str) -> None:
        if self._client is None:
            raise RuntimeError(
                "MCP email provider is not configured — set MCP_EMAIL_ENABLED=true and "
                "provide a server connection"
            )
        self._client.send_email(to=to, subject=subject, body=body)
