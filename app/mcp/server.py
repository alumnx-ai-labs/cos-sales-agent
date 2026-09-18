# app/mcp/server.py
import os
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config.settings import get_settings
from app.database.mongodb import get_client, initialize_database
from app.email.models import Email
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.llm_provider import LLMProvider
from app.mcp import tools
from app.providers.factory import ProviderFactory


@lru_cache
def _get_db():
    settings = get_settings()
    return initialize_database(get_client(settings.mongodb_uri), settings.mongodb_database)


@lru_cache
def _get_llm_provider() -> LLMProvider:
    return ProviderFactory.create_llm_provider(get_settings())


@lru_cache
def _get_calendar_provider() -> CalendarProvider:
    return ProviderFactory.create_calendar_provider(get_settings())


mcp = FastMCP("cos-sales-agent")


@mcp.tool()
def process_email(email: Email) -> dict[str, Any]:
    """Run one Gmail message through the sales-agent pipeline: normalization, thread
    resolution, LLM analysis, cumulative context, knowledge extraction/deduplication,
    meeting detection, and reply drafting. Persists everything to MongoDB. Returns
    structured results -- including a proposed reply draft and/or meeting proposal for
    you to review and act on via your Gmail connector. Never sends email or creates
    calendar events itself.

    Map Gmail fields into the input shape as follows:
    - message_id: Gmail message id (or Message-ID header)
    - thread_id: Gmail thread id, if available (omit if unknown -- the pipeline will
      infer one)
    - from/to/cc: {"name": ..., "email": ...} objects
    - timestamp: ISO-8601 datetime string
    - in_reply_to / references: Message-ID header values, if available
    """
    return tools.process_email(
        _get_db(), email, _get_llm_provider(), _get_calendar_provider(), get_settings()
    )


@mcp.tool()
def list_processed_emails(limit: int = 50) -> list[dict[str, Any]]:
    """List emails already ingested via process_email, most recent first.

    Only shows emails that have already been processed by this tool -- it never reads
    Gmail directly. Each entry includes message_id, thread_id, from/to/cc, subject,
    timestamp, processing_status, the thread's current summary, and a body_preview
    truncated to about 150 characters. The full email body is never returned.

    Each entry also includes record_id, source_type, source_link, date, goal_pillar,
    label_applied, confidence, and entities_referenced (a dict of people/projects/
    commitments/follow_ups/meetings/personal id lists) -- these are populated once the
    email reaches the ENTITIES_PROCESSED stage, and are None (or empty lists, for
    entities_referenced) for an email that hasn't gotten there yet.
    """
    return tools.list_processed_emails(_get_db(), limit)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("PORT", 8000))
        secret = os.environ.get("MCP_URL_SECRET")
        if not secret:
            raise RuntimeError("MCP_URL_SECRET is required when MCP_TRANSPORT=streamable-http")
        mcp.settings.streamable_http_path = f"/{secret}/mcp"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
