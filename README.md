# CoS Sales Agent

A local, modular Chief-of-Staff Sales Sub-Agent prototype. It processes sales emails,
threads conversations, builds cumulative per-thread context with an LLM, extracts and
deduplicates sales knowledge, drafts replies, detects meetings, and prepares
approval-gated calendar actions — backed by MongoDB with a Streamlit dashboard.

External actions (sending an email, creating a calendar event) always require explicit
human approval; everything else runs automatically.

## Architecture

See `docs/superpowers/specs/2026-09-13-cos-sales-agent-design.md` for the full data model
and design rationale. In short:

```
Email Provider -> validate -> normalize -> thread -> LLM analysis -> cumulative context
   -> knowledge extraction/deduplication -> reply draft / meeting detection
   -> (human approval) -> send email / create calendar event
```

## Prerequisites

- Python 3.11+
- Docker (for MongoDB) — or a MongoDB instance you already run locally
- No API keys are required for demo mode

## Installation

```bash
git clone <this-repository>
cd cos-sales-agent
python -m venv .venv
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

**macOS/Linux:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## MongoDB

```bash
docker compose up -d
```

This starts MongoDB on `localhost:27017` and Mongo Express (a MongoDB inspection UI) on
`http://localhost:8081`. Collections and indexes are created automatically by the
application on startup — no manual MongoDB setup is required.

### Running Without Docker (Windows, no admin rights)

Docker is used for exactly one thing in this project: giving you a MongoDB instance at
`localhost:27017` (Mongo Express is an optional inspection UI — the Streamlit dashboard
already covers that). If Docker/WSL/Hyper-V aren't available (e.g. a locked-down office
laptop), run MongoDB directly instead — no installer, no Windows service, no admin rights:

```powershell
.\run-mongodb-local.ps1
```

This downloads the official MongoDB Community Server **ZIP** build (not the MSI
installer — the MSI is the one that needs admin rights to register a service) into
`%USERPROFILE%\mongodb`, and starts `mongod.exe` as a normal foreground process bound to
`127.0.0.1:27017`. Leave that terminal window open while you use the app. Everything else
— `.env`, `python main.py --healthcheck`, `--mode=demo`, the Streamlit dashboard — works
completely unchanged, since the app only ever talks to `MONGODB_URI` and doesn't know or
care whether MongoDB came from Docker or a local `mongod.exe`.

## Environment Configuration

Edit `.env` (copied from `.env.example`). Defaults already run the full demo with zero
credentials:

```env
EMAIL_PROVIDER=demo
CALENDAR_PROVIDER=mock
LLM_PROVIDER=mock
SIMULATION_MODE=true
DEMO_SEED=42
```

## Health Check

```bash
python main.py --healthcheck
```

Verifies configuration, MongoDB connectivity/indexes, and provider selection.

## Demo Mode

```bash
python main.py --mode=demo
```

Processes a deterministic 9-email synthetic sales thread end to end: threading, LLM-style
analysis, cumulative context, context diffs, knowledge extraction/deduplication,
contradiction/history tracking, reply drafting, meeting detection, and prepared (but
unapproved) calendar actions.

## Streamlit Dashboard

```bash
streamlit run app/ui/dashboard.py
```

Inspect processed emails, thread context evolution, deduplicated knowledge (with history),
and approve/edit/reject reply drafts and calendar actions from the UI.

## Running Tests

```bash
pytest
```

All tests run against `mongomock` and mock LLM/email/calendar providers — no real
credentials or external services are required.

## Database Reset

```bash
python main.py --reset-demo
```

Only permitted when `APP_ENV=development` or `SIMULATION_MODE=true`; clears demo data
from every collection so a fresh `--mode=demo` run starts clean.

## MCP Configuration (extension point, not ready-to-use)

`EMAIL_PROVIDER=mcp` / `CALENDAR_PROVIDER=mcp` are an **extension point**, not a
pre-wired, zero-config integration: this codebase ships the `MCPEmailProvider` /
`MCPCalendarProvider` adapter shape, but no connection to any specific mail or calendar
server. Selecting `mcp` requires:

1. Setting `MCP_EMAIL_ENABLED=true` / `MCP_CALENDAR_ENABLED=true` — `ProviderFactory`
   raises a clear `ValueError` at startup if the corresponding provider is set to `mcp`
   without its `*_ENABLED` flag, rather than constructing a provider that only fails
   later on first use.
2. Supplying your own MCP client instance to the adapter (e.g. by extending
   `ProviderFactory` to construct `MCPEmailProvider(client=...)` /
   `MCPCalendarProvider(client=...)`) — the adapters are constructed with `client=None` by
   default and raise `RuntimeError` on first use until a real client is wired in.

The core pipeline has no dependency on MCP being available — `ProviderFactory` only
imports the MCP adapter module when explicitly selected, so an unconfigured MCP server
never breaks demo/mock runs.

## LLM Configuration

Set `LLM_PROVIDER=claude` or `LLM_PROVIDER=openai` plus `LLM_API_KEY` and `LLM_MODEL` to
use a real model instead of the deterministic mock.

## Safety / Approval Model

- Reading, analyzing, threading, context-building, knowledge extraction/deduplication,
  reply drafting, and meeting detection are fully automatic.
- Sending an email and creating a calendar event always require explicit approval through
  the Streamlit UI.
- In this version, an approved reply is always **simulated** — printed to the console and
  marked `simulated_sent` — regardless of the `SIMULATION_MODE` setting; there is no
  real-send code path wired into the approval flow yet (see `app/replies/approval.py`'s
  `simulate_send`). `SIMULATION_MODE` currently only gates `--reset-demo` (it must be
  `true`, or `APP_ENV=development`, for that command to run). A calendar event created via
  an enabled MCP calendar provider is a real external action once approved.
- Calendar events are created for the authenticated user only — external attendees
  (sender, customer, CC) can never be added; this is enforced by a Pydantic validator and
  a second check immediately before the calendar provider is called.

## Portability

No hardcoded paths, usernames, personal emails, API keys, or MongoDB credentials appear
anywhere in the source — everything environment-specific comes from `.env`. This project
should run unmodified after cloning to another Windows, macOS, or Linux machine, provided
Docker and Python 3.11+ are available.

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
$env:PYTHONPATH = (Get-Location).Path
mcp dev app/mcp/server.py
```

Opens the MCP Inspector in your browser. Under the "Tools" tab you should see
`process_email` with its full input schema; you can invoke it there with a sample email
payload and confirm new documents appear in your local `cos_sales` MongoDB database.

## Troubleshooting

- **MongoDB connection refused**: confirm `docker compose up -d` succeeded and
  `MONGODB_URI` in `.env` matches the exposed port.
- **`--healthcheck` reports MongoDB failure**: check Docker is running and port 27017 is
  free.
- **Demo run produces 0 completed emails**: check `LOG_LEVEL=DEBUG` in `.env` and inspect
  console output for the failing stage.
- **Streamlit shows a blank dashboard**: run `python main.py --mode=demo` first to
  populate MongoDB.

## Adding a New Provider

Implement the relevant interface (`EmailProvider`, `CalendarProvider`, or `LLMProvider`
from `app/interfaces/`), add it under `app/providers/<kind>/`, and add a branch for it in
`app/providers/factory.py`'s `ProviderFactory`. Business logic never imports a concrete
provider directly, so no other file needs to change.
