# Local MCP Server for Claude Desktop's Gmail Connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing sales-agent pipeline as a local MCP server with one tool, `process_email`, that Claude Desktop can call after reading a Gmail message via its own built-in Gmail connector.

**Architecture:** Two new files only (`app/mcp/tools.py`, `app/mcp/server.py`) — `tools.process_email` wraps the single incoming email in the existing `MockEmailProvider` and calls the existing, unmodified `run_pipeline`, then reads back the resulting thread context/knowledge/reply draft/calendar proposal from the existing repositories; `server.py` is a thin `FastMCP` wrapper exposing that function as a stdio-transport MCP tool. Nothing in `app/pipeline.py`, `app/config/settings.py`, or `app/providers/factory.py` changes.

**Tech Stack:** Python 3.11+, the official `mcp` SDK (`mcp.server.fastmcp.FastMCP`), existing Pydantic/pymongo/mongomock/pytest stack.

**Spec:** `docs/superpowers/specs/2026-09-15-mcp-gmail-connector-design.md`

## Global Constraints

- No Gmail API client, Google OAuth credentials, or `google-api-python-client` anywhere in this change — Claude Desktop's built-in Gmail connector handles all Gmail read/send.
- No changes to `app/pipeline.py`, `app/config/settings.py`, `app/providers/factory.py`, `app/providers/email/mcp.py`, or `app/providers/calendar/mcp.py` — all stay byte-for-byte as they are today.
- No calendar event creation from the new code path — `CalendarProvider.create_event()` must never be reachable from anything under `app/mcp/`.
- No Docker/WSL — the server is a plain local Python process; MongoDB is already running locally at `mongodb://localhost:27017`.
- `app/mcp/tools.py` must not import the `mcp` SDK package — it must stay testable with plain `mongomock` + mock providers, exactly like every other module in the test suite.
- The tool's parameter type is `app.email.models.Email` directly — no duplicate schema.
- Every existing test must still pass unmodified after this change.

---

## Task 1: Pure Pipeline-Wrapping Logic (`app/mcp/tools.py`)

**Files:**
- Create: `app/mcp/__init__.py`
- Create: `app/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `Email` (`app.email.models`), `run_pipeline` (`app.pipeline`), `MockEmailProvider` (`app.providers.email.mock`), `ContextSnapshotRepository`/`KnowledgeRepository`/`ReplyDraftRepository`/`CalendarActionRepository` (`app.database.repositories`), `LLMProvider`/`CalendarProvider` (`app.interfaces`), `Settings` (`app.config.settings`) — all existing, unmodified.
- Produces: `process_email(db: Database, email: Email, llm_provider: LLMProvider, calendar_provider: CalendarProvider, settings: Settings) -> dict[str, Any]` in `app.mcp.tools`, with the exact return shape documented below. Task 2 imports this function directly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_tools.py
import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.email.models import parse_email
from app.interfaces.llm_provider import LLMProvider
from app.mcp.tools import process_email
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.llm.mock import MockLLMProvider


def _raw_email(message_id, body, subject="Enterprise CRM Proposal", **overrides):
    raw = {
        "message_id": message_id,
        "from": {"name": "John", "email": "john@example.com"},
        "to": [{"name": "Ashok", "email": "ashok@example.com"}],
        "subject": subject,
        "body": body,
        "timestamp": "2026-09-13T10:30:00Z",
    }
    raw.update(overrides)
    return raw


class _AlwaysBrokenLLM(LLMProvider):
    def analyze_email(self, email):
        return {"summary": "not enough fields"}

    def update_context(self, previous_context, new_analysis):
        raise AssertionError("should not be reached when analysis fails")

    def verify_same_fact(self, existing_value, new_value, subject, predicate):
        raise AssertionError

    def draft_reply(self, context, latest_email):
        raise AssertionError


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


@pytest.fixture
def settings():
    return Settings(calendar_provider="mock", llm_provider="mock")


def test_process_email_returns_draft_and_knowledge_for_buying_signal(db, settings):
    email = parse_email(
        _raw_email(
            "msg_001",
            "We currently use Salesforce but pricing has become a real pain point. "
            "Could you send over pricing?",
        )
    )

    result = process_email(db, email, MockLLMProvider(), MockCalendarProvider(), settings)

    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["thread_id"] is not None
    assert result["reply_draft"] is not None
    assert result["reply_draft"]["subject"].startswith("Re:")
    assert any(item["current_value"] == "Salesforce" for item in result["knowledge"])
    assert result["calendar_proposal"] is None


def test_process_email_is_idempotent_on_replay(db, settings):
    raw = _raw_email("msg_001", "We currently use Salesforce but pricing is a pain point.")

    first = process_email(db, parse_email(raw), MockLLMProvider(), MockCalendarProvider(), settings)
    second = process_email(db, parse_email(raw), MockLLMProvider(), MockCalendarProvider(), settings)

    assert first["status"] == "completed"
    assert second["status"] == "skipped"
    assert second["thread_id"] == first["thread_id"]
    assert second["knowledge"] == first["knowledge"]


def test_process_email_surfaces_meeting_proposal_without_scheduling_it(db, settings):
    email = parse_email(
        _raw_email("msg_001", "Let's meet Tuesday at 3 PM for 30 minutes to discuss pricing.")
    )
    calendar_provider = MockCalendarProvider()

    result = process_email(db, email, MockLLMProvider(), calendar_provider, settings)

    assert result["status"] == "completed"
    assert result["calendar_proposal"] is not None
    assert result["calendar_proposal"]["status"] == "awaiting_approval"
    assert calendar_provider.created_events == []


def test_process_email_returns_failed_status_with_error_on_analysis_failure(db, settings):
    email = parse_email(_raw_email("msg_001", "Some body text."))

    result = process_email(db, email, _AlwaysBrokenLLM(), MockCalendarProvider(), settings)

    assert result["status"] == "failed"
    assert result["error"] is not None
    assert result["thread_id"] is None
    assert result["knowledge"] == []
    assert result["reply_draft"] is None
    assert result["calendar_proposal"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp'`

- [ ] **Step 3: Implement `app/mcp/tools.py`**

```python
# app/mcp/__init__.py
```

```python
# app/mcp/tools.py
from typing import Any

from pymongo.database import Database

from app.config.settings import Settings
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    KnowledgeRepository,
    ReplyDraftRepository,
)
from app.email.models import Email
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.llm_provider import LLMProvider
from app.pipeline import run_pipeline
from app.providers.email.mock import MockEmailProvider

_PENDING_CALENDAR_STATUSES = ("awaiting_approval", "needs_clarification")


def _empty_result(status: str, error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "error": error,
        "thread_id": None,
        "context_summary": None,
        "knowledge": [],
        "reply_draft": None,
        "calendar_proposal": None,
    }


def process_email(
    db: Database,
    email: Email,
    llm_provider: LLMProvider,
    calendar_provider: CalendarProvider,
    settings: Settings,
) -> dict[str, Any]:
    raw = email.model_dump(mode="json", by_alias=True)
    provider = MockEmailProvider(payloads=[raw])
    summary = run_pipeline(db, provider, llm_provider, calendar_provider, settings)
    result = summary.results[0]

    if result.final_stage == "FAILED":
        return _empty_result("failed", result.error)

    snapshot = ContextSnapshotRepository(db).find_one({"triggering_email_id": email.message_id})
    thread_id = snapshot["thread_id"] if snapshot else None

    knowledge = KnowledgeRepository(db).all_for_thread(thread_id) if thread_id else []
    draft = ReplyDraftRepository(db).find_one({"source_email_id": email.message_id})
    calendar_actions = (
        CalendarActionRepository(db).find_many({"thread_id": thread_id}) if thread_id else []
    )
    pending_calendar = next(
        (a for a in calendar_actions if a["status"] in _PENDING_CALENDAR_STATUSES), None
    )

    return {
        "status": result.final_stage.lower(),
        "error": None,
        "thread_id": thread_id,
        "context_summary": snapshot["context"]["summary"] if snapshot else None,
        "knowledge": [
            {
                "subject_key": k["subject_key"],
                "predicate": k["predicate"],
                "current_value": k["current_value"],
                "basis": k["basis"],
                "confidence": k["confidence"],
            }
            for k in knowledge
        ],
        "reply_draft": draft["draft"] if draft else None,
        "calendar_proposal": (
            {
                "status": pending_calendar["status"],
                "title": pending_calendar["event"]["title"],
                "start": pending_calendar["event"]["start"],
                "end": pending_calendar["event"]["end"],
                "timezone": pending_calendar["event"]["timezone"],
                "reason": pending_calendar.get("reason"),
            }
            if pending_calendar
            else None
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (every existing test plus the 4 new ones)

- [ ] **Step 6: Commit**

```bash
git add app/mcp/__init__.py app/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat: add process_email MCP tool logic wrapping the existing pipeline"
```

---

## Task 2: FastMCP Server Wiring (`app/mcp/server.py`)

**Files:**
- Modify: `requirements.txt`
- Create: `app/mcp/server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `process_email` (`app.mcp.tools`, from Task 1), `get_settings` (`app.config.settings`), `get_client`/`initialize_database` (`app.database.mongodb`), `ProviderFactory` (`app.providers.factory`), `Email` (`app.email.models`) — all existing, unmodified.
- Produces: a module-level `mcp: FastMCP` instance with a registered `process_email` tool, and a `main()` function that runs it over stdio. Nothing downstream depends on this module (it is the entrypoint).

- [ ] **Step 1: Add the `mcp` SDK dependency and install it**

Add this line to `requirements.txt` (after the `python-dotenv` line):

```text
mcp[cli]
```

Run: `pip install -r requirements.txt`

Run: `python -c "from mcp.server.fastmcp import FastMCP; print('ok')"`
Expected: prints `ok`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_mcp_server.py
import asyncio

from app.mcp.server import mcp


def test_process_email_tool_is_registered():
    registered_tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in registered_tools]
    assert "process_email" in names
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp.server'`

- [ ] **Step 4: Implement `app/mcp/server.py`**

```python
# app/mcp/server.py
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (every existing test plus the 5 new ones from Tasks 1-2)

- [ ] **Step 7: Manually verify the server over stdio (MongoDB must already be running locally)**

Run: `mcp dev app/mcp/server.py`
Expected: opens the MCP Inspector in your browser; the "Tools" tab lists `process_email` with the input schema derived from `Email` (including the `from`/`to`/`cc` nested objects). This step is exploratory/manual — there is no automated assertion for it.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt app/mcp/server.py tests/test_mcp_server.py
git commit -m "feat: expose process_email as a local stdio MCP server for Claude Desktop"
```

---

## Task 3: Claude Desktop Setup Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only)
- Produces: nothing consumed by other tasks

- [ ] **Step 1: Add a "Claude Desktop MCP Integration" section to `README.md`**

Insert this new section immediately before the existing `## Troubleshooting` section:

```markdown
## Claude Desktop MCP Integration

This project can run as a local MCP server that Claude Desktop calls directly. Claude
Desktop's built-in Gmail connector handles all Gmail reading and sending; this server only
ever runs the existing pipeline (analysis, context, knowledge extraction/deduplication,
meeting detection, reply drafting) against whatever email Claude hands it, and persists the
result to your local MongoDB. It never talks to Gmail, the Gmail API, or any OAuth flow, and
it never creates a real calendar event.

### Prerequisites

- MongoDB running locally (see the MongoDB section above)
- `.env` configured with a real LLM provider, since the MCP tool uses `ClaudeProvider`:

```env
LLM_PROVIDER=claude
LLM_API_KEY=<your Anthropic API key>
LLM_MODEL=claude-sonnet-5
```

### Install

```powershell
pip install -r requirements.txt
```

### Register the server with Claude Desktop

Add this to Claude Desktop's `claude_desktop_config.json` (Windows:
`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cos-sales-agent": {
      "command": "C:\\path\\to\\cos-sales-agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.server"],
      "cwd": "C:\\path\\to\\cos-sales-agent"
    }
  }
}
```

Replace both paths with your actual project location, then restart Claude Desktop. The
server starts automatically as a subprocess Claude Desktop manages — there is no separate
"run the server" step.

### What the `process_email` tool does

Given one email's fields (sender, recipients, subject, body, timestamp, message id), it
runs the full pipeline and returns:
- a running summary of what's known about the thread so far
- deduplicated sales knowledge extracted from the thread
- a proposed reply draft (if one is warranted) — for Claude to send via its own Gmail
  connector, under Claude's normal approval prompt
- a proposed meeting time (if detected) — informational only; no calendar event is ever
  created by this tool

### Manual verification

```powershell
mcp dev app/mcp/server.py
```

Opens the MCP Inspector in your browser. Under the "Tools" tab you should see
`process_email` with its full input schema; you can invoke it there with a sample email
payload and confirm new documents appear in your local `cos_sales` MongoDB database.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document Claude Desktop MCP server setup"
```
