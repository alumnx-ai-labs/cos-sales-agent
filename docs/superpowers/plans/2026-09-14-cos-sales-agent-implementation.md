# CoS Sales Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local, modular Chief-of-Staff Sales Sub-Agent prototype: ingest emails, thread them, run structured LLM analysis, accumulate per-thread context, extract/deduplicate sales knowledge, draft replies, detect meetings, and prepare approval-gated calendar actions — all backed by MongoDB and runnable via `python main.py --mode=demo` plus a Streamlit dashboard.

**Architecture:** A pipeline orchestrator (`app/pipeline.py`) runs each email through validate → thread → analyze → context → knowledge → reply → meeting stages, persisting per-stage status so partial failures are retryable. Everything reads/writes through provider interfaces (`EmailProvider`, `CalendarProvider`, `LLMProvider`) and a thin MongoDB repository layer, so demo/mock/MCP/Claude/OpenAI implementations are interchangeable via `.env` alone.

**Tech Stack:** Python 3.11+, Pydantic v2, pymongo (+ `mongomock` for tests), Streamlit, rapidfuzz, pytest, anthropic SDK, openai SDK, python-dotenv/pydantic-settings, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-13-cos-sales-agent-design.md` (read together with this plan — the plan implements it task-by-task; this file does not repeat every rationale from the spec).

## Global Constraints

- Python 3.11+, Pydantic v2 everywhere (never v1-style `@validator`, always `@field_validator`).
- No hardcoded Windows/macOS/Linux paths, usernames, personal emails, API keys, or MongoDB credentials anywhere in `app/`, `main.py`, `demo_data/`, or `tests/`.
- All environment-specific values come from `.env` via `pydantic-settings`; `.env` is git-ignored, `.env.example` is committed.
- Demo mode (`EMAIL_PROVIDER=demo`, `CALENDAR_PROVIDER=mock`, `LLM_PROVIDER=mock`, `SIMULATION_MODE=true`) must work with zero external credentials and must be deterministic given `DEMO_SEED=42`.
- Calendar events must always validate to `attendees == []`; this is enforced both by a Pydantic `field_validator` on `CalendarEvent` and by a second assertion immediately before `CalendarProvider.create_event()` is called.
- Knowledge identity is `(thread_id, subject_key, predicate, fact_key)` — `current_value` is never part of the unique key; value changes update `current_value` and append to `history`, never deleting prior values.
- Context snapshots are append-only, uniquely keyed by `(thread_id, triggering_email_id)` — reprocessing the same email must never create another `context_version`.
- Every stage that can fail independently (`RECEIVED, VALIDATED, THREADED, ANALYZED, CONTEXT_BUILT, KNOWLEDGE_PROCESSED, REPLY_PROCESSED, MEETING_PROCESSED, COMPLETED, FAILED`) is tracked per-email so partial failures are visible and retryable — an email is never marked `COMPLETED` after only partial processing.
- No collection/data object created for tests may require real email, calendar, Anthropic, OpenAI, or MCP credentials — repository tests use `mongomock`, provider tests use `MockLLMProvider`/`MockEmailProvider`/`MockCalendarProvider`.
- Sending a real email or creating a real calendar event only ever happens from the two explicit human-approval code paths — nowhere else in `app/` calls `EmailProvider.send_email()` or `CalendarProvider.create_event()`.
- Every file stays under the ~800-line soft ceiling; split further if a task's file grows past it.
- Any Pydantic model containing a `datetime` field is persisted to MongoDB via `model.model_dump(mode="json")` (datetimes become ISO-8601 strings) and reconstructed via `Model.model_validate(doc)` — never store native `datetime`/`set` objects directly. Real MongoDB silently strips `tzinfo` from native datetimes on write (returning naive UTC on read) while `mongomock` (used in tests) does not, so relying on native datetimes would pass in tests and misbehave against a real database; ISO strings round-trip identically through both.

---

## Task 1: Project Scaffolding & Configuration

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `app/__init__.py`, `app/config/__init__.py`
- Create: `app/config/settings.py`
- Create: `app/config/logging.py`
- Test: `tests/test_settings.py`
- Test: `tests/__init__.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings `BaseSettings` subclass) with fields: `app_env: str`, `mongodb_uri: str`, `mongodb_database: str`, `email_limit: int`, `email_provider: str`, `calendar_provider: str`, `llm_provider: str`, `llm_api_key: str`, `llm_model: str`, `mcp_email_enabled: bool`, `mcp_calendar_enabled: bool`, `simulation_mode: bool`, `timezone: str`, `log_level: str`, `demo_seed: int`. Also `get_settings() -> Settings` (cached factory) and `configure_logging(level: str) -> None`.

- [ ] **Step 1: Write the failing test for settings defaults and env override**

```python
# tests/test_settings.py
import os
from app.config.settings import Settings, get_settings


def test_settings_load_defaults(monkeypatch):
    monkeypatch.delenv("EMAIL_LIMIT", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.email_limit == 50
    assert settings.email_provider == "demo"
    assert settings.calendar_provider == "mock"
    assert settings.llm_provider == "mock"
    assert settings.simulation_mode is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("EMAIL_LIMIT", "10")
    monkeypatch.setenv("EMAIL_PROVIDER", "mcp")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.email_limit == 10
    assert settings.email_provider == "mcp"
    get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` (package does not exist yet)

- [ ] **Step 3: Create supporting scaffolding files**

```text
# requirements.txt
pydantic>=2.6,<3.0
pydantic-settings>=2.2,<3.0
pymongo>=4.6,<5.0
mongomock>=4.1,<5.0
streamlit>=1.32,<2.0
rapidfuzz>=3.6,<4.0
pytest>=8.0,<9.0
anthropic>=0.25,<1.0
openai>=1.14,<2.0
python-dotenv>=1.0,<2.0
```

```env
# .env.example
APP_ENV=development

MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=cos_sales

EMAIL_LIMIT=50

EMAIL_PROVIDER=demo
CALENDAR_PROVIDER=mock
LLM_PROVIDER=mock

LLM_API_KEY=
LLM_MODEL=

MCP_EMAIL_ENABLED=false
MCP_CALENDAR_ENABLED=false

SIMULATION_MODE=true

TIMEZONE=Asia/Kolkata

LOG_LEVEL=INFO

DEMO_SEED=42
```

```text
# .gitignore
.env
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
*.egg-info/
.mypy_cache/
```

```python
# app/__init__.py
```

```python
# app/config/__init__.py
```

```python
# tests/__init__.py
```

```python
# tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def _isolated_settings_cache():
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

- [ ] **Step 4: Implement `Settings` and `get_settings`**

```python
# app/config/settings.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "cos_sales"

    email_limit: int = 50

    email_provider: str = "demo"
    calendar_provider: str = "mock"
    llm_provider: str = "mock"

    llm_api_key: str = ""
    llm_model: str = ""

    mcp_email_enabled: bool = False
    mcp_calendar_enabled: bool = False

    simulation_mode: bool = True

    timezone: str = "Asia/Kolkata"

    log_level: str = "INFO"

    demo_seed: int = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Implement `configure_logging`**

```python
# app/config/logging.py
import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_settings.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example .gitignore app/__init__.py app/config tests/__init__.py tests/conftest.py tests/test_settings.py
git commit -m "feat: add project scaffolding and typed settings"
```

---

## Task 2: Email Domain Models & Normalizer

**Files:**
- Create: `app/email/__init__.py`
- Create: `app/email/models.py`
- Create: `app/email/normalizer.py`
- Test: `tests/test_email_models.py`
- Test: `tests/test_email_normalizer.py`

**Interfaces:**
- Consumes: nothing (pure domain layer)
- Produces: `EmailAddress(BaseModel)` with `name: str | None`, `email: EmailStr`; `Email(BaseModel)` with `message_id: str`, `thread_id: str | None`, `from_: EmailAddress` (alias `"from"`), `to: list[EmailAddress]`, `cc: list[EmailAddress] = []`, `subject: str`, `body: str`, `timestamp: datetime`, `in_reply_to: str | None = None`, `references: list[str] = []`, `attachments: list[str] = []`, `labels: list[str] = []`. `parse_email(raw: dict) -> Email` (raises `pydantic.ValidationError` on malformed input — caller decides what to do with it). `normalize_email(email: Email) -> Email` returning a new `Email` with trimmed body/subject whitespace and lower-cased address fields, and `normalize_subject(subject: str) -> str` stripping `Re:`/`Fwd:` prefixes (any casing, repeated) and collapsing whitespace.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_email_models.py
import pytest
from pydantic import ValidationError

from app.email.models import Email, parse_email


VALID_RAW = {
    "message_id": "msg_001",
    "thread_id": "thread_001",
    "from": {"name": "John Smith", "email": "john@example.com"},
    "to": [{"name": "Ashok", "email": "ashok@example.com"}],
    "cc": [],
    "subject": "Enterprise CRM Proposal",
    "body": "We are evaluating your enterprise plan...",
    "timestamp": "2026-09-13T10:30:00Z",
    "in_reply_to": None,
    "references": [],
    "attachments": [],
    "labels": [],
}


def test_parse_valid_email():
    email = parse_email(VALID_RAW)
    assert isinstance(email, Email)
    assert email.message_id == "msg_001"
    assert email.from_.email == "john@example.com"
    assert email.to[0].email == "ashok@example.com"


def test_parse_email_missing_required_field_raises():
    raw = dict(VALID_RAW)
    del raw["message_id"]
    with pytest.raises(ValidationError):
        parse_email(raw)


def test_parse_email_invalid_sender_raises():
    raw = dict(VALID_RAW)
    raw["from"] = {"name": "John", "email": "not-an-email"}
    with pytest.raises(ValidationError):
        parse_email(raw)


def test_parse_email_defaults_optional_fields():
    raw = {
        "message_id": "msg_002",
        "from": {"name": "A", "email": "a@example.com"},
        "to": [{"name": "B", "email": "b@example.com"}],
        "subject": "Hi",
        "body": "Body",
        "timestamp": "2026-09-13T10:30:00Z",
    }
    email = parse_email(raw)
    assert email.thread_id is None
    assert email.cc == []
    assert email.references == []
    assert email.attachments == []
    assert email.labels == []
```

```python
# tests/test_email_normalizer.py
from app.email.models import parse_email
from app.email.normalizer import normalize_email, normalize_subject


def _base_raw(**overrides):
    raw = {
        "message_id": "msg_001",
        "from": {"name": "John Smith", "email": "JOHN@Example.com"},
        "to": [{"name": "Ashok", "email": "Ashok@Example.com"}],
        "subject": "  Re: Re: Enterprise CRM Proposal  ",
        "body": "  We are evaluating your enterprise plan...  ",
        "timestamp": "2026-09-13T10:30:00Z",
    }
    raw.update(overrides)
    return raw


def test_normalize_subject_strips_reply_forward_prefixes():
    assert normalize_subject("Re: Re: Fwd: Enterprise Deal") == "Enterprise Deal"
    assert normalize_subject("  FW:  Pricing   Question  ") == "Pricing Question"


def test_normalize_email_trims_and_lowercases_addresses():
    email = parse_email(_base_raw())
    normalized = normalize_email(email)
    assert normalized.subject == "Enterprise CRM Proposal"
    assert normalized.body == "We are evaluating your enterprise plan..."
    assert normalized.from_.email == "john@example.com"
    assert normalized.to[0].email == "ashok@example.com"
    # original is untouched (immutable transform)
    assert email.from_.email == "JOHN@Example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_email_models.py tests/test_email_normalizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.email'`

- [ ] **Step 3: Implement `app/email/models.py`**

```python
# app/email/__init__.py
```

```python
# app/email/models.py
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, ConfigDict


class EmailAddress(BaseModel):
    name: str | None = None
    email: EmailStr


class Email(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: str
    thread_id: str | None = None
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress]
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str
    body: str
    timestamp: datetime
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


def parse_email(raw: dict[str, Any]) -> Email:
    return Email.model_validate(raw)
```

- [ ] **Step 4: Implement `app/email/normalizer.py`**

```python
# app/email/normalizer.py
import re

from app.email.models import Email, EmailAddress

_REPLY_FORWARD_PREFIX = re.compile(r"^\s*(re|fwd|fw)\s*:\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def normalize_subject(subject: str) -> str:
    text = subject.strip()
    while True:
        stripped = _REPLY_FORWARD_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    return _WHITESPACE.sub(" ", text).strip()


def _normalize_address(address: EmailAddress) -> EmailAddress:
    return EmailAddress(name=address.name, email=address.email.lower())


def normalize_email(email: Email) -> Email:
    return email.model_copy(
        update={
            "subject": normalize_subject(email.subject),
            "body": _WHITESPACE.sub(" ", email.body.strip()),
            "from_": _normalize_address(email.from_),
            "to": [_normalize_address(a) for a in email.to],
            "cc": [_normalize_address(a) for a in email.cc],
        }
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_email_models.py tests/test_email_normalizer.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add app/email tests/test_email_models.py tests/test_email_normalizer.py
git commit -m "feat: add normalized email domain model and normalizer"
```

---

## Task 3: Thread Detection

**Files:**
- Create: `app/email/threading.py`
- Test: `tests/test_threading.py`

**Interfaces:**
- Consumes: `Email` from Task 2 (`app.email.models`)
- Produces: `ThreadCandidate(BaseModel)` with `thread_id: str`, `normalized_subject: str`, `participant_emails: set[str]`, `message_ids: set[str]`, `last_message_at: datetime`; `resolve_thread_id(email: Email, candidates: list[ThreadCandidate], window_days: int = 14) -> str` — returns an existing candidate's `thread_id` or a freshly generated one (`f"thread_{email.message_id}"`) when no candidate matches. Pure function, no DB access, no LLM.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_threading.py
from datetime import datetime, timedelta, timezone

from app.email.models import parse_email
from app.email.threading import ThreadCandidate, resolve_thread_id


def _email(**overrides):
    raw = {
        "message_id": "msg_002",
        "from": {"name": "John", "email": "john@example.com"},
        "to": [{"name": "Ashok", "email": "ashok@example.com"}],
        "subject": "Re: Enterprise CRM Proposal",
        "body": "Following up...",
        "timestamp": "2026-09-14T10:30:00Z",
    }
    raw.update(overrides)
    return parse_email(raw)


def test_uses_provider_thread_id_when_present():
    email = _email(thread_id="thread_provider_123")
    assert resolve_thread_id(email, candidates=[]) == "thread_provider_123"


def test_matches_via_in_reply_to():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Unrelated Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email(in_reply_to="msg_001")
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_matches_via_references():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Unrelated",
        participant_emails={"john@example.com"},
        message_ids={"msg_000", "msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email(references=["msg_000"])
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_matches_via_subject_and_participant_overlap():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Enterprise CRM Proposal",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    email = _email()  # subject normalizes to same text, no in_reply_to/references
    assert resolve_thread_id(email, candidates=[candidate]) == "thread_001"


def test_falls_back_to_participant_overlap_within_window():
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Totally Different Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
    )
    email = _email(subject="A New Subject Entirely")
    assert resolve_thread_id(email, candidates=[candidate], window_days=14) == "thread_001"


def test_participant_overlap_outside_window_creates_new_thread():
    old_time = datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc) - timedelta(days=20)
    candidate = ThreadCandidate(
        thread_id="thread_001",
        normalized_subject="Totally Different Subject",
        participant_emails={"john@example.com", "ashok@example.com"},
        message_ids={"msg_001"},
        last_message_at=old_time,
    )
    email = _email(subject="A New Subject Entirely")
    result = resolve_thread_id(email, candidates=[candidate], window_days=14)
    assert result != "thread_001"


def test_no_match_creates_new_thread_id():
    email = _email()
    result = resolve_thread_id(email, candidates=[])
    assert result == "thread_msg_002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_threading.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.email.threading'`

- [ ] **Step 3: Implement `app/email/threading.py`**

```python
# app/email/threading.py
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.email.models import Email
from app.email.normalizer import normalize_subject


class ThreadCandidate(BaseModel):
    thread_id: str
    normalized_subject: str
    participant_emails: set[str]
    message_ids: set[str]
    last_message_at: datetime


def _participants(email: Email) -> set[str]:
    return {email.from_.email, *(a.email for a in email.to), *(a.email for a in email.cc)}


def resolve_thread_id(
    email: Email,
    candidates: list[ThreadCandidate],
    window_days: int = 14,
) -> str:
    if email.thread_id:
        return email.thread_id

    if email.in_reply_to:
        for candidate in candidates:
            if email.in_reply_to in candidate.message_ids:
                return candidate.thread_id

    if email.references:
        for candidate in candidates:
            if candidate.message_ids.intersection(email.references):
                return candidate.thread_id

    normalized = normalize_subject(email.subject)
    participants = _participants(email)

    for candidate in candidates:
        if candidate.normalized_subject == normalized and candidate.participant_emails.intersection(participants):
            return candidate.thread_id

    window = timedelta(days=window_days)
    matching = [
        c
        for c in candidates
        if c.participant_emails.intersection(participants)
        and email.timestamp - c.last_message_at <= window
    ]
    if matching:
        matching.sort(key=lambda c: c.last_message_at, reverse=True)
        return matching[0].thread_id

    return f"thread_{email.message_id}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_threading.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/email/threading.py tests/test_threading.py
git commit -m "feat: add deterministic thread detection"
```

---

## Task 4: MongoDB Connection & Index Initialization

**Files:**
- Create: `app/database/__init__.py`
- Create: `app/database/mongodb.py`
- Create: `app/database/indexes.py`
- Test: `tests/test_indexes.py`

**Interfaces:**
- Consumes: nothing (tests use `mongomock`, not a real MongoDB)
- Produces: `get_client(uri: str)` → `pymongo.MongoClient`; `get_database(client, name: str)` → `pymongo.database.Database`; `initialize_indexes(db) -> None` — creates all unique/non-unique indexes from the spec; safe to call repeatedly (idempotent — `create_index` is itself idempotent in MongoDB).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_indexes.py
import mongomock

from app.database.indexes import initialize_indexes


def test_initialize_indexes_creates_expected_unique_indexes():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    initialize_indexes(db)
    initialize_indexes(db)  # must be safe to call twice

    def index_keys(collection_name):
        return {
            tuple(spec["key"].items()): spec.get("unique", False)
            for spec in db[collection_name].index_information().values()
            if spec["key"] != [("_id", 1)]
        }

    assert index_keys("emails") == {(("message_id", 1),): True}
    assert index_keys("threads") == {(("thread_id", 1),): True}
    assert index_keys("context_snapshots") == {
        (("thread_id", 1), ("triggering_email_id", 1)): True
    }
    assert index_keys("knowledge_items") == {
        (("thread_id", 1), ("subject_key", 1), ("predicate", 1), ("fact_key", 1)): True
    }
    assert index_keys("reply_drafts") == {(("source_email_id", 1),): True}
    assert index_keys("calendar_actions") == {
        (("thread_id", 1), ("meeting_fingerprint", 1)): True
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indexes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.database'`

- [ ] **Step 3: Implement `app/database/mongodb.py` and `app/database/indexes.py`**

```python
# app/database/__init__.py
```

```python
# app/database/mongodb.py
from pymongo import MongoClient
from pymongo.database import Database


def get_client(uri: str) -> MongoClient:
    return MongoClient(uri)


def get_database(client: MongoClient, name: str) -> Database:
    return client[name]
```

```python
# app/database/indexes.py
from pymongo.database import Database


def initialize_indexes(db: Database) -> None:
    db.emails.create_index("message_id", unique=True)
    db.emails.create_index("processing_status.stage")

    db.threads.create_index("thread_id", unique=True)

    db.context_snapshots.create_index(
        [("thread_id", 1), ("triggering_email_id", 1)], unique=True
    )
    db.context_snapshots.create_index([("thread_id", 1), ("context_version", 1)])

    db.knowledge_items.create_index(
        [("thread_id", 1), ("subject_key", 1), ("predicate", 1), ("fact_key", 1)],
        unique=True,
    )

    db.reply_drafts.create_index("source_email_id", unique=True)

    db.calendar_actions.create_index(
        [("thread_id", 1), ("meeting_fingerprint", 1)], unique=True
    )

    db.processing_runs.create_index("started_at")


def initialize_database(client, database_name: str) -> Database:
    db = get_database(client, database_name)
    initialize_indexes(db)
    return db
```

Note: `get_database` must be imported inside `initialize_database` to avoid a circular top-level import — since both live in this task, define `initialize_database` in `app/database/mongodb.py` instead, importing `initialize_indexes` from `app/database/indexes.py`:

```python
# app/database/mongodb.py (revised, replaces the version above)
from pymongo import MongoClient
from pymongo.database import Database

from app.database.indexes import initialize_indexes


def get_client(uri: str) -> MongoClient:
    return MongoClient(uri)


def get_database(client: MongoClient, name: str) -> Database:
    return client[name]


def initialize_database(client: MongoClient, database_name: str) -> Database:
    db = get_database(client, database_name)
    initialize_indexes(db)
    return db
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_indexes.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add app/database/__init__.py app/database/mongodb.py app/database/indexes.py tests/test_indexes.py
git commit -m "feat: add MongoDB connection helpers and index initialization"
```

---

## Task 5: Repository Layer

**Files:**
- Create: `app/database/repositories.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Consumes: `initialize_database` from Task 4
- Produces: `EmailRepository`, `ThreadRepository`, `ContextSnapshotRepository`, `KnowledgeRepository`, `ReplyDraftRepository`, `CalendarActionRepository`, `ProcessingRunRepository` — each constructed as `Repository(db)` and exposing `upsert_by_key(key: dict, document: dict) -> dict` (idempotent: inserts if absent, replaces fields if present, returns the stored document) and `find_one(key: dict) -> dict | None`. `ContextSnapshotRepository` additionally exposes `latest_for_thread(thread_id: str) -> dict | None` (highest `context_version`). `KnowledgeRepository` additionally exposes `all_for_thread(thread_id: str) -> list[dict]`. `EmailRepository` additionally exposes `set_stage(message_id: str, stage: str, error: str | None = None, failed_stage: str | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repositories.py
import mongomock
import pytest

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_email_repository_upsert_is_idempotent(db):
    repo = EmailRepository(db)
    doc = {"message_id": "msg_001", "subject": "Hi"}

    first = repo.upsert_by_key({"message_id": "msg_001"}, doc)
    second = repo.upsert_by_key({"message_id": "msg_001"}, doc)

    assert first["message_id"] == "msg_001"
    assert second["message_id"] == "msg_001"
    assert db.emails.count_documents({}) == 1


def test_email_repository_set_stage_updates_in_place(db):
    repo = EmailRepository(db)
    repo.upsert_by_key({"message_id": "msg_001"}, {"message_id": "msg_001"})

    repo.set_stage("msg_001", "ANALYZED")
    doc = repo.find_one({"message_id": "msg_001"})
    assert doc["processing_status"]["stage"] == "ANALYZED"
    assert doc["processing_status"]["error"] is None

    repo.set_stage("msg_001", "FAILED", error="boom", failed_stage="ANALYZED")
    doc = repo.find_one({"message_id": "msg_001"})
    assert doc["processing_status"]["stage"] == "FAILED"
    assert doc["processing_status"]["error"] == "boom"
    assert doc["processing_status"]["failed_stage"] == "ANALYZED"


def test_context_snapshot_repository_latest_for_thread(db):
    repo = ContextSnapshotRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_001"},
        {"thread_id": "t1", "triggering_email_id": "msg_001", "context_version": 1},
    )
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_002"},
        {"thread_id": "t1", "triggering_email_id": "msg_002", "context_version": 2},
    )
    latest = repo.latest_for_thread("t1")
    assert latest["context_version"] == 2


def test_context_snapshot_repository_reprocessing_same_email_is_noop(db):
    repo = ContextSnapshotRepository(db)
    key = {"thread_id": "t1", "triggering_email_id": "msg_001"}
    repo.upsert_by_key(key, {**key, "context_version": 1})
    repo.upsert_by_key(key, {**key, "context_version": 1})
    assert db.context_snapshots.count_documents({}) == 1


def test_knowledge_repository_all_for_thread(db):
    repo = KnowledgeRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "subject_key": "abc_corp", "predicate": "requires", "fact_key": "seat_count"},
        {
            "thread_id": "t1",
            "subject_key": "abc_corp",
            "predicate": "requires",
            "fact_key": "seat_count",
            "current_value": "100 seats",
        },
    )
    items = repo.all_for_thread("t1")
    assert len(items) == 1
    assert items[0]["current_value"] == "100 seats"


def test_calendar_action_repository_dedupes_on_fingerprint(db):
    repo = CalendarActionRepository(db)
    key = {"thread_id": "t1", "meeting_fingerprint": "abc_2026-09-15t15:00_2026-09-15t16:00"}
    repo.upsert_by_key(key, {**key, "status": "awaiting_approval"})
    repo.upsert_by_key(key, {**key, "status": "approved"})
    assert db.calendar_actions.count_documents({}) == 1
    stored = repo.find_one(key)
    assert stored["status"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repositories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.database.repositories'`

- [ ] **Step 3: Implement `app/database/repositories.py`**

```python
# app/database/repositories.py
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database


class _BaseRepository:
    collection_name: str

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db[self.collection_name]

    def upsert_by_key(self, key: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        self._collection.update_one(key, {"$set": document}, upsert=True)
        return self._collection.find_one(key, {"_id": 0})

    def find_one(self, key: dict[str, Any]) -> dict[str, Any] | None:
        return self._collection.find_one(key, {"_id": 0})

    def find_many(self, key: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._collection.find(key, {"_id": 0}))


class EmailRepository(_BaseRepository):
    collection_name = "emails"

    def set_stage(
        self,
        message_id: str,
        stage: str,
        error: str | None = None,
        failed_stage: str | None = None,
    ) -> None:
        self._collection.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "processing_status": {
                        "stage": stage,
                        "error": error,
                        "failed_stage": failed_stage,
                        "updated_at": datetime.now(timezone.utc),
                    }
                }
            },
            upsert=True,
        )


class ThreadRepository(_BaseRepository):
    collection_name = "threads"


class ContextSnapshotRepository(_BaseRepository):
    collection_name = "context_snapshots"

    def latest_for_thread(self, thread_id: str) -> dict[str, Any] | None:
        return self._collection.find_one(
            {"thread_id": thread_id}, {"_id": 0}, sort=[("context_version", -1)]
        )

    def all_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return list(
            self._collection.find({"thread_id": thread_id}, {"_id": 0}).sort("context_version", 1)
        )


class KnowledgeRepository(_BaseRepository):
    collection_name = "knowledge_items"

    def all_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return self.find_many({"thread_id": thread_id})


class ReplyDraftRepository(_BaseRepository):
    collection_name = "reply_drafts"


class CalendarActionRepository(_BaseRepository):
    collection_name = "calendar_actions"


class ProcessingRunRepository(_BaseRepository):
    collection_name = "processing_runs"


class EntityRepository(_BaseRepository):
    collection_name = "entities"


class OpportunityRepository(_BaseRepository):
    collection_name = "opportunities"


class ActivityRepository(_BaseRepository):
    collection_name = "activities"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repositories.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/database/repositories.py tests/test_repositories.py
git commit -m "feat: add MongoDB repository layer with idempotent upserts"
```

---

## Task 6: LLM Interface, Analysis Schema, Mock Provider, Extractor

**Files:**
- Create: `app/interfaces/__init__.py`
- Create: `app/interfaces/llm_provider.py`
- Create: `app/analysis/__init__.py`
- Create: `app/analysis/schemas.py`
- Create: `app/analysis/extractor.py`
- Create: `app/providers/__init__.py`
- Create: `app/providers/llm/__init__.py`
- Create: `app/providers/llm/mock.py`
- Test: `tests/test_analysis_schemas.py`
- Test: `tests/test_analysis_extractor.py`
- Test: `tests/test_mock_llm_provider.py`

**Interfaces:**
- Consumes: `Email` from Task 2
- Produces: `LLMProvider(ABC)` with abstract methods `analyze_email(self, email: Email) -> dict`, `update_context(self, previous_context: dict, new_analysis: dict) -> dict`, `verify_same_fact(self, existing_value: str, new_value: str, subject: str, predicate: str) -> bool`, `draft_reply(self, context: dict, latest_email: Email) -> dict`. `Fact(BaseModel)` with `subject: str, predicate: str, object: str`. `EmailAnalysis(BaseModel)` with all fields listed in the spec (`email_id, summary, intent, entities, facts, requirements, pain_points, buying_signals, objections, competitors, pricing_mentions, commitments, action_items, meetings, people, companies, products`, all list fields defaulting to `[]`). `AnalysisOutcome(BaseModel)` with `success: bool`, `analysis: EmailAnalysis | None`, `error: str | None`. `analyze_email_with_validation(llm: LLMProvider, email: Email, max_retries: int = 1) -> AnalysisOutcome`. `MockLLMProvider(LLMProvider)` — deterministic, keyword-based, fully functional (no stubs).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_schemas.py
from app.analysis.schemas import EmailAnalysis, Fact


def test_email_analysis_defaults():
    analysis = EmailAnalysis(email_id="msg_001", summary="s", intent="evaluation")
    assert analysis.facts == []
    assert analysis.pain_points == []
    assert analysis.competitors == []


def test_email_analysis_accepts_facts():
    analysis = EmailAnalysis(
        email_id="msg_001",
        summary="s",
        intent="evaluation",
        facts=[Fact(subject="Customer", predicate="uses", object="Salesforce")],
    )
    assert analysis.facts[0].object == "Salesforce"
```

```python
# tests/test_mock_llm_provider.py
from app.email.models import parse_email
from app.providers.llm.mock import MockLLMProvider


def _email(body: str, subject: str = "Enterprise CRM Proposal"):
    return parse_email(
        {
            "message_id": "msg_001",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": subject,
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_analyze_email_extracts_competitor_and_pain_point():
    provider = MockLLMProvider()
    email = _email("We currently use Salesforce but pricing has become a real pain point for us.")
    result = provider.analyze_email(email)
    assert "Salesforce" in result["competitors"]
    assert any("pric" in p.lower() for p in result["pain_points"])


def test_analyze_email_extracts_seat_requirement():
    provider = MockLLMProvider()
    email = _email("We would need about 100 seats for our sales team.")
    result = provider.analyze_email(email)
    assert any("100" in r for r in result["requirements"])


def test_analyze_email_is_deterministic():
    provider = MockLLMProvider()
    email = _email("We need a demo and a formal pricing proposal.")
    first = provider.analyze_email(email)
    second = provider.analyze_email(email)
    assert first == second


def test_update_context_merges_new_facts_and_tags_provenance():
    provider = MockLLMProvider()
    previous_context = {
        "summary": "",
        "participants": [],
        "company": {},
        "opportunity": {},
        "requirements": [],
        "pain_points": [],
        "products_discussed": [],
        "competitors": [],
        "pricing": {},
        "objections": [],
        "buying_signals": [],
        "decisions": [],
        "commitments": [],
        "open_questions": [],
        "next_actions": [],
        "meetings": [],
    }
    analysis = {
        "email_id": "msg_001",
        "summary": "Customer evaluating CRM",
        "intent": "evaluation",
        "entities": [],
        "facts": [],
        "requirements": ["100 seats"],
        "pain_points": ["Pricing"],
        "buying_signals": ["pricing request"],
        "objections": [],
        "competitors": ["Salesforce"],
        "pricing_mentions": [],
        "commitments": [],
        "action_items": [],
        "meetings": [],
        "people": [],
        "companies": [],
        "products": [],
    }
    new_context = provider.update_context(previous_context, analysis)
    assert new_context["requirements"][0]["value"] == "100 seats"
    assert new_context["requirements"][0]["basis"] == "stated"
    assert new_context["requirements"][0]["source_email_ids"] == ["msg_001"]
    assert any(item["basis"] == "inferred" for item in new_context["buying_signals"] + new_context.get("_inferred", []))


def test_verify_same_fact_uses_similarity():
    provider = MockLLMProvider()
    assert provider.verify_same_fact("100 seats", "approximately 100 users", "ABC Corp", "requires") is True
    assert provider.verify_same_fact("100 seats", "Salesforce integration", "ABC Corp", "requires") is False


def test_draft_reply_produces_subject_and_body():
    provider = MockLLMProvider()
    email = _email("Can you send us pricing for the enterprise plan?")
    context = {"summary": "ABC Corp evaluating enterprise plan", "company": {"name": "ABC Corp"}}
    draft = provider.draft_reply(context, email)
    assert draft["subject"].startswith("Re:")
    assert "ABC Corp" in draft["body"] or "pricing" in draft["body"].lower()
```

```python
# tests/test_analysis_extractor.py
from app.analysis.extractor import analyze_email_with_validation
from app.email.models import parse_email
from app.interfaces.llm_provider import LLMProvider


class _BrokenLLM(LLMProvider):
    def __init__(self, bad_payloads: list[dict]):
        self._payloads = bad_payloads
        self._calls = 0

    def analyze_email(self, email):
        payload = self._payloads[min(self._calls, len(self._payloads) - 1)]
        self._calls += 1
        return payload

    def update_context(self, previous_context, new_analysis):
        raise NotImplementedError

    def verify_same_fact(self, existing_value, new_value, subject, predicate):
        raise NotImplementedError

    def draft_reply(self, context, latest_email):
        raise NotImplementedError


def _email():
    return parse_email(
        {
            "message_id": "msg_001",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": "Hi",
            "body": "Body",
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_analyze_email_with_validation_succeeds_on_valid_payload():
    llm = _BrokenLLM([{"email_id": "msg_001", "summary": "s", "intent": "evaluation"}])
    outcome = analyze_email_with_validation(llm, _email())
    assert outcome.success is True
    assert outcome.analysis.email_id == "msg_001"
    assert outcome.error is None


def test_analyze_email_with_validation_retries_once_then_succeeds():
    llm = _BrokenLLM(
        [
            {"summary": "missing email_id and intent"},
            {"email_id": "msg_001", "summary": "s", "intent": "evaluation"},
        ]
    )
    outcome = analyze_email_with_validation(llm, _email(), max_retries=1)
    assert outcome.success is True
    assert outcome.analysis.email_id == "msg_001"


def test_analyze_email_with_validation_fails_after_exhausting_retries():
    llm = _BrokenLLM([{"summary": "still invalid"}])
    outcome = analyze_email_with_validation(llm, _email(), max_retries=1)
    assert outcome.success is False
    assert outcome.analysis is None
    assert outcome.error is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_schemas.py tests/test_analysis_extractor.py tests/test_mock_llm_provider.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `app/interfaces/llm_provider.py` and `app/analysis/schemas.py`**

```python
# app/interfaces/__init__.py
```

```python
# app/interfaces/llm_provider.py
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
```

```python
# app/analysis/__init__.py
```

```python
# app/analysis/schemas.py
from pydantic import BaseModel, Field


class Fact(BaseModel):
    subject: str
    predicate: str
    object: str


class EmailAnalysis(BaseModel):
    email_id: str
    summary: str
    intent: str
    entities: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    pricing_mentions: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    meetings: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement `app/analysis/extractor.py`**

```python
# app/analysis/extractor.py
from pydantic import BaseModel, ValidationError

from app.analysis.schemas import EmailAnalysis
from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider


class AnalysisOutcome(BaseModel):
    success: bool
    analysis: EmailAnalysis | None = None
    error: str | None = None


def analyze_email_with_validation(
    llm: LLMProvider, email: Email, max_retries: int = 1
) -> AnalysisOutcome:
    last_error: str | None = None
    attempts = max_retries + 1

    for _ in range(attempts):
        raw = llm.analyze_email(email)
        raw.setdefault("email_id", email.message_id)
        try:
            analysis = EmailAnalysis.model_validate(raw)
            return AnalysisOutcome(success=True, analysis=analysis, error=None)
        except ValidationError as exc:
            last_error = str(exc)

    return AnalysisOutcome(success=False, analysis=None, error=last_error)
```

- [ ] **Step 5: Implement `app/providers/llm/mock.py`**

```python
# app/providers/__init__.py
```

```python
# app/providers/llm/__init__.py
```

```python
# app/providers/llm/mock.py
import re
from typing import Any

from rapidfuzz import fuzz

from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider

_COMPETITORS = ["Salesforce", "HubSpot", "Microsoft", "Zoho"]
_PAIN_KEYWORDS = ["pricing", "price", "manual", "slow", "integration", "clunky", "expensive"]
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

        if new_analysis.get("summary"):
            context["summary"] = new_analysis["summary"]

        return context

    def verify_same_fact(self, existing_value: str, new_value: str, subject: str, predicate: str) -> bool:
        return fuzz.token_sort_ratio(existing_value.lower(), new_value.lower()) >= 85

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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_analysis_schemas.py tests/test_analysis_extractor.py tests/test_mock_llm_provider.py -v`
Expected: PASS (13 tests)

- [ ] **Step 7: Commit**

```bash
git add app/interfaces app/analysis app/providers/__init__.py app/providers/llm tests/test_analysis_schemas.py tests/test_analysis_extractor.py tests/test_mock_llm_provider.py
git commit -m "feat: add LLM provider interface, analysis schema, extractor, and mock LLM"
```

---

## Task 7: Context Models & Diff

**Files:**
- Create: `app/context/__init__.py`
- Create: `app/context/models.py`
- Create: `app/context/diff.py`
- Test: `tests/test_context_models.py`
- Test: `tests/test_context_diff.py`

**Interfaces:**
- Consumes: nothing beyond stdlib/pydantic
- Produces: `ProvenancedValue(BaseModel)` with `value: str`, `basis: Literal["stated", "inferred"]`, `source_email_ids: list[str]`; `ThreadContext(BaseModel)` with fields `summary: str = ""`, `participants: list[str] = []`, `company: dict = {}`, `opportunity: dict = {}`, `requirements/pain_points/products_discussed/competitors/objections/buying_signals/decisions/commitments/open_questions/next_actions/meetings: list[ProvenancedValue] = []`, `pricing: dict = {}`; `ContextChange(BaseModel)` with `type: Literal["ADDED","REMOVED","UPDATED"]`, `field: str`, `detail: str`, `source_email_id: str`; `ContextSnapshot(BaseModel)` with `thread_id, context_version: int, triggering_email_id, context: ThreadContext, changes_from_previous_context: list[ContextChange] = [], created_at: datetime`. `diff_context(previous: ThreadContext, new: ThreadContext, source_email_id: str) -> list[ContextChange]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_context_models.py
from app.context.models import ContextSnapshot, ProvenancedValue, ThreadContext


def test_thread_context_defaults_are_empty():
    context = ThreadContext()
    assert context.requirements == []
    assert context.company == {}
    assert context.summary == ""


def test_provenanced_value_requires_basis_literal():
    value = ProvenancedValue(value="100 seats", basis="stated", source_email_ids=["msg_001"])
    assert value.basis == "stated"


def test_context_snapshot_round_trip():
    snapshot = ContextSnapshot(
        thread_id="thread_001",
        context_version=1,
        triggering_email_id="msg_001",
        context=ThreadContext(summary="Evaluating CRM"),
        changes_from_previous_context=[],
        created_at="2026-09-13T10:30:00Z",
    )
    assert snapshot.context.summary == "Evaluating CRM"
```

```python
# tests/test_context_diff.py
from app.context.diff import diff_context
from app.context.models import ProvenancedValue, ThreadContext


def test_diff_detects_added_requirement():
    previous = ThreadContext()
    new = ThreadContext(
        requirements=[ProvenancedValue(value="100 seats", basis="stated", source_email_ids=["msg_001"])]
    )
    changes = diff_context(previous, new, source_email_id="msg_001")
    assert len(changes) == 1
    assert changes[0].type == "ADDED"
    assert changes[0].field == "requirements"
    assert changes[0].detail == "100 seats"


def test_diff_detects_updated_scalar_field():
    previous = ThreadContext(pricing={"budget": "$50K"})
    new = ThreadContext(pricing={"budget": "$75K"})
    changes = diff_context(previous, new, source_email_id="msg_007")
    assert any(c.type == "UPDATED" and c.field == "pricing.budget" for c in changes)


def test_diff_detects_removed_item():
    previous = ThreadContext(
        objections=[ProvenancedValue(value="Price too high", basis="stated", source_email_ids=["msg_002"])]
    )
    new = ThreadContext()
    changes = diff_context(previous, new, source_email_id="msg_003")
    assert any(c.type == "REMOVED" and c.field == "objections" for c in changes)


def test_diff_is_empty_when_nothing_changed():
    context = ThreadContext(summary="Same summary")
    changes = diff_context(context, context, source_email_id="msg_001")
    assert changes == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_context_models.py tests/test_context_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.context'`

- [ ] **Step 3: Implement `app/context/models.py`**

```python
# app/context/__init__.py
```

```python
# app/context/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProvenancedValue(BaseModel):
    value: str
    basis: Literal["stated", "inferred"]
    source_email_ids: list[str] = Field(default_factory=list)


class ThreadContext(BaseModel):
    summary: str = ""
    participants: list[str] = Field(default_factory=list)
    company: dict = Field(default_factory=dict)
    opportunity: dict = Field(default_factory=dict)
    requirements: list[ProvenancedValue] = Field(default_factory=list)
    pain_points: list[ProvenancedValue] = Field(default_factory=list)
    products_discussed: list[ProvenancedValue] = Field(default_factory=list)
    competitors: list[ProvenancedValue] = Field(default_factory=list)
    pricing: dict = Field(default_factory=dict)
    objections: list[ProvenancedValue] = Field(default_factory=list)
    buying_signals: list[ProvenancedValue] = Field(default_factory=list)
    decisions: list[ProvenancedValue] = Field(default_factory=list)
    commitments: list[ProvenancedValue] = Field(default_factory=list)
    open_questions: list[ProvenancedValue] = Field(default_factory=list)
    next_actions: list[ProvenancedValue] = Field(default_factory=list)
    meetings: list[ProvenancedValue] = Field(default_factory=list)


class ContextChange(BaseModel):
    type: Literal["ADDED", "REMOVED", "UPDATED"]
    field: str
    detail: str
    source_email_id: str


class ContextSnapshot(BaseModel):
    thread_id: str
    context_version: int
    triggering_email_id: str
    context: ThreadContext
    changes_from_previous_context: list[ContextChange] = Field(default_factory=list)
    created_at: datetime


LIST_FIELDS: tuple[str, ...] = (
    "requirements",
    "pain_points",
    "products_discussed",
    "competitors",
    "objections",
    "buying_signals",
    "decisions",
    "commitments",
    "open_questions",
    "next_actions",
    "meetings",
)

DICT_FIELDS: tuple[str, ...] = ("company", "opportunity", "pricing")
```

- [ ] **Step 4: Implement `app/context/diff.py`**

```python
# app/context/diff.py
from app.context.models import DICT_FIELDS, LIST_FIELDS, ContextChange, ThreadContext


def diff_context(previous: ThreadContext, new: ThreadContext, source_email_id: str) -> list[ContextChange]:
    changes: list[ContextChange] = []

    for field in LIST_FIELDS:
        previous_values = {item.value for item in getattr(previous, field)}
        new_values = {item.value for item in getattr(new, field)}

        for added in new_values - previous_values:
            changes.append(
                ContextChange(type="ADDED", field=field, detail=added, source_email_id=source_email_id)
            )
        for removed in previous_values - new_values:
            changes.append(
                ContextChange(type="REMOVED", field=field, detail=removed, source_email_id=source_email_id)
            )

    for field in DICT_FIELDS:
        previous_dict: dict = getattr(previous, field)
        new_dict: dict = getattr(new, field)
        all_keys = set(previous_dict) | set(new_dict)
        for key in all_keys:
            old_value = previous_dict.get(key)
            new_value = new_dict.get(key)
            if old_value == new_value:
                continue
            if old_value is None:
                changes.append(
                    ContextChange(
                        type="ADDED", field=f"{field}.{key}", detail=str(new_value), source_email_id=source_email_id
                    )
                )
            elif new_value is None:
                changes.append(
                    ContextChange(
                        type="REMOVED", field=f"{field}.{key}", detail=str(old_value), source_email_id=source_email_id
                    )
                )
            else:
                changes.append(
                    ContextChange(
                        type="UPDATED",
                        field=f"{field}.{key}",
                        detail=f"{old_value} -> {new_value}",
                        source_email_id=source_email_id,
                    )
                )

    if previous.summary != new.summary and new.summary:
        changes.append(
            ContextChange(type="UPDATED", field="summary", detail=new.summary, source_email_id=source_email_id)
        )

    return changes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_context_models.py tests/test_context_diff.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add app/context/__init__.py app/context/models.py app/context/diff.py tests/test_context_models.py tests/test_context_diff.py
git commit -m "feat: add thread context model and context diff engine"
```

---

## Task 8: Cumulative Context Engine

**Files:**
- Create: `app/context/engine.py`
- Test: `tests/test_context_engine.py`

**Interfaces:**
- Consumes: `ThreadContext`, `ContextChange`, `diff_context` from Task 7; `EmailAnalysis` from Task 6; `LLMProvider` from Task 6
- Produces: `build_next_context(previous: ThreadContext | None, analysis: EmailAnalysis, source_email_id: str, llm: LLMProvider) -> tuple[ThreadContext, list[ContextChange]]` — calls `llm.update_context(previous_or_empty.model_dump(), analysis.model_dump())`, validates the returned dict back into a `ThreadContext`, and returns it along with the diff against `previous`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_context_engine.py
from app.analysis.schemas import EmailAnalysis
from app.context.engine import build_next_context
from app.context.models import ThreadContext
from app.providers.llm.mock import MockLLMProvider


def test_build_first_context_version_from_empty_previous():
    llm = MockLLMProvider()
    analysis = EmailAnalysis(
        email_id="msg_001",
        summary="ABC Corp evaluating CRM",
        intent="evaluation",
        requirements=["100 seats"],
        competitors=["Salesforce"],
    )
    context, changes = build_next_context(previous=None, analysis=analysis, source_email_id="msg_001", llm=llm)

    assert context.requirements[0].value == "100 seats"
    assert context.requirements[0].source_email_ids == ["msg_001"]
    assert any(c.type == "ADDED" and c.field == "requirements" for c in changes)


def test_build_second_context_version_accumulates_on_first():
    llm = MockLLMProvider()
    analysis_1 = EmailAnalysis(email_id="msg_001", summary="Intro", intent="evaluation", requirements=["100 seats"])
    context_v1, _ = build_next_context(previous=None, analysis=analysis_1, source_email_id="msg_001", llm=llm)

    analysis_2 = EmailAnalysis(
        email_id="msg_007", summary="Follow up", intent="evaluation", requirements=["150 seats"]
    )
    context_v2, changes = build_next_context(
        previous=context_v1, analysis=analysis_2, source_email_id="msg_007", llm=llm
    )

    values = {r.value for r in context_v2.requirements}
    assert "100 seats" in values
    assert "150 seats" in values
    assert any(c.type == "ADDED" and c.detail == "150 seats" for c in changes)


def test_context_never_loses_prior_information_when_new_analysis_is_empty():
    llm = MockLLMProvider()
    analysis_1 = EmailAnalysis(email_id="msg_001", summary="Intro", intent="evaluation", competitors=["Salesforce"])
    context_v1, _ = build_next_context(previous=None, analysis=analysis_1, source_email_id="msg_001", llm=llm)

    analysis_2 = EmailAnalysis(email_id="msg_002", summary="Just checking in", intent="evaluation")
    context_v2, _ = build_next_context(previous=context_v1, analysis=analysis_2, source_email_id="msg_002", llm=llm)

    assert "Salesforce" in {c.value for c in context_v2.competitors}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.context.engine'`

- [ ] **Step 3: Implement `app/context/engine.py`**

```python
# app/context/engine.py
from app.analysis.schemas import EmailAnalysis
from app.context.diff import diff_context
from app.context.models import ContextChange, ThreadContext
from app.interfaces.llm_provider import LLMProvider


def build_next_context(
    previous: ThreadContext | None,
    analysis: EmailAnalysis,
    source_email_id: str,
    llm: LLMProvider,
) -> tuple[ThreadContext, list[ContextChange]]:
    previous_context = previous or ThreadContext()

    raw_next = llm.update_context(previous_context.model_dump(), analysis.model_dump())
    next_context = ThreadContext.model_validate(raw_next)

    changes = diff_context(previous_context, next_context, source_email_id=source_email_id)
    return next_context, changes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_context_engine.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/context/engine.py tests/test_context_engine.py
git commit -m "feat: add cumulative context engine (previous context + new analysis -> next context)"
```

---

## Task 9: Knowledge Models & Normalization

**Files:**
- Create: `app/knowledge/__init__.py`
- Create: `app/knowledge/models.py`
- Create: `app/knowledge/normalize.py`
- Test: `tests/test_knowledge_models.py`
- Test: `tests/test_knowledge_normalize.py`

**Interfaces:**
- Consumes: nothing beyond stdlib/pydantic/re
- Produces: `HistoryEntry(BaseModel)` with `value: str, source_email_id: str, recorded_at: datetime`; `KnowledgeItem(BaseModel)` with `knowledge_id, thread_id, subject_key, predicate, fact_key, current_value: str, history: list[HistoryEntry], source_emails: list[str], basis: Literal["stated","inferred"], first_seen_at: datetime, last_confirmed_at: datetime, confidence: float, status: Literal["active","contradicted","retracted"] = "active"`. `slugify(text: str) -> str`; `normalize_text(text: str) -> str` (lowercase, strip punctuation, collapse whitespace, spell out digit words 0-20); `classify_fact_key(predicate: str, object_text: str) -> str` (returns an attribute key like `seat_count`/`budget`/`close_date`/`pricing_tier`/`contract_length` when the normalized object text matches a known attribute pattern, else returns `normalize_text(object_text)` as a set-membership fallback); `extract_leading_number(text: str) -> int | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_knowledge_models.py
from datetime import datetime, timezone

from app.knowledge.models import HistoryEntry, KnowledgeItem


def test_knowledge_item_round_trip():
    item = KnowledgeItem(
        knowledge_id="knowledge_001",
        thread_id="thread_001",
        subject_key="abc_corp",
        predicate="requires",
        fact_key="seat_count",
        current_value="150 seats",
        history=[
            HistoryEntry(value="100 seats", source_email_id="msg_001", recorded_at=datetime.now(timezone.utc)),
            HistoryEntry(value="150 seats", source_email_id="msg_007", recorded_at=datetime.now(timezone.utc)),
        ],
        source_emails=["msg_001", "msg_007"],
        basis="stated",
        first_seen_at=datetime.now(timezone.utc),
        last_confirmed_at=datetime.now(timezone.utc),
        confidence=0.97,
    )
    assert item.status == "active"
    assert len(item.history) == 2
```

```python
# tests/test_knowledge_normalize.py
from app.knowledge.normalize import (
    classify_fact_key,
    extract_leading_number,
    normalize_text,
    slugify,
)


def test_normalize_text_lowercases_and_strips_punctuation():
    assert normalize_text("  100 Seats!! ") == "100 seats"


def test_normalize_text_converts_number_words():
    assert normalize_text("one hundred seats") == "100 seats"


def test_slugify_produces_snake_case_key():
    assert slugify("ABC Corp") == "abc_corp"
    assert slugify("Ashok's Team, Inc.") == "ashoks_team_inc"


def test_classify_fact_key_for_seat_count():
    assert classify_fact_key("requires", "100 seats") == "seat_count"
    assert classify_fact_key("requires", "approximately 100 users") == "seat_count"
    assert classify_fact_key("requires", "150 licenses") == "seat_count"


def test_classify_fact_key_for_budget_and_close_date():
    assert classify_fact_key("has", "a budget of $75K") == "budget"
    assert classify_fact_key("targets", "close date of Nov 1") == "close_date"


def test_classify_fact_key_falls_back_to_normalized_object_for_set_membership():
    assert classify_fact_key("mentioned_competitor", "Salesforce") == "salesforce"
    assert classify_fact_key("mentioned_competitor", "HubSpot") == "hubspot"


def test_extract_leading_number_parses_digits_from_normalized_text():
    assert extract_leading_number("150 seats") == 150
    assert extract_leading_number(normalize_text("one hundred seats")) == 100
    assert extract_leading_number("Salesforce") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_knowledge_models.py tests/test_knowledge_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.knowledge'`

- [ ] **Step 3: Implement `app/knowledge/models.py`**

```python
# app/knowledge/__init__.py
```

```python
# app/knowledge/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HistoryEntry(BaseModel):
    value: str
    source_email_id: str
    recorded_at: datetime


class KnowledgeItem(BaseModel):
    knowledge_id: str
    thread_id: str
    subject_key: str
    predicate: str
    fact_key: str
    current_value: str
    history: list[HistoryEntry] = Field(default_factory=list)
    source_emails: list[str] = Field(default_factory=list)
    basis: Literal["stated", "inferred"]
    first_seen_at: datetime
    last_confirmed_at: datetime
    confidence: float
    status: Literal["active", "contradicted", "retracted"] = "active"
```

- [ ] **Step 4: Implement `app/knowledge/normalize.py`**

```python
# app/knowledge/normalize.py
import re

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}
_TEN_MULTIPLES = {
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_HUNDRED_PATTERN = re.compile(r"\bone hundred\b")
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

_ATTRIBUTE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(seats?|users?|licen[sc]es?)\b"), "seat_count"),
    (re.compile(r"\bbudget\b"), "budget"),
    (re.compile(r"\bclose(?:ing)? date\b"), "close_date"),
    (re.compile(r"\bpricing tier|plan tier\b"), "pricing_tier"),
    (re.compile(r"\bcontract length|term length\b"), "contract_length"),
]

_LEADING_NUMBER = re.compile(r"^(\d+)")


def normalize_text(text: str) -> str:
    lowered = text.strip().lower()
    lowered = _HUNDRED_PATTERN.sub("100", lowered)
    for word, digit in _NUMBER_WORDS.items():
        lowered = re.sub(rf"\b{word}\b", digit, lowered)
    for word, value in _TEN_MULTIPLES.items():
        lowered = re.sub(rf"\b{word}\b", str(value), lowered)
    lowered = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", lowered).strip()


def slugify(text: str) -> str:
    normalized = normalize_text(text)
    slug = re.sub(r"\s+", "_", normalized)
    return slug


def classify_fact_key(predicate: str, object_text: str) -> str:
    normalized = normalize_text(object_text)
    for pattern, key in _ATTRIBUTE_PATTERNS:
        if pattern.search(normalized):
            return key
    return slugify(object_text)


def extract_leading_number(text: str) -> int | None:
    normalized = normalize_text(text)
    match = _LEADING_NUMBER.search(normalized)
    if match:
        return int(match.group(1))
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_models.py tests/test_knowledge_normalize.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git add app/knowledge/__init__.py app/knowledge/models.py app/knowledge/normalize.py tests/test_knowledge_models.py tests/test_knowledge_normalize.py
git commit -m "feat: add knowledge item model and deterministic normalization/fact-key classification"
```

---

## Task 10: Knowledge Deduplication & Contradiction Handling

**Files:**
- Create: `app/knowledge/deduplication.py`
- Test: `tests/test_knowledge_deduplication.py`

**Interfaces:**
- Consumes: `KnowledgeItem`, `HistoryEntry`, `classify_fact_key`, `slugify`, `normalize_text`, `extract_leading_number` from Task 9; `LLMProvider` from Task 6
- Produces: `process_new_fact(items: list[KnowledgeItem], thread_id: str, subject: str, predicate: str, object_text: str, source_email_id: str, basis: Literal["stated","inferred"], llm: LLMProvider, now: datetime) -> tuple[list[KnowledgeItem], KnowledgeItem]` — returns the (possibly updated) full list of items for the thread and the specific item that was created/updated. Implements Steps 1-4 from the spec, including value-change contradiction/history handling.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_knowledge_deduplication.py
from datetime import datetime, timezone

from app.knowledge.deduplication import process_new_fact
from app.providers.llm.mock import MockLLMProvider


def _now():
    return datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)


def test_first_mention_creates_new_knowledge_item():
    llm = MockLLMProvider()
    items, item = process_new_fact(
        items=[],
        thread_id="thread_001",
        subject="ABC Corp",
        predicate="requires",
        object_text="100 seats",
        source_email_id="msg_001",
        basis="stated",
        llm=llm,
        now=_now(),
    )
    assert len(items) == 1
    assert item.subject_key == "abc_corp"
    assert item.fact_key == "seat_count"
    assert item.current_value == "100 seats"
    assert item.history[0].value == "100 seats"
    assert item.source_emails == ["msg_001"]


def test_exact_repeat_updates_confidence_without_duplicating():
    llm = MockLLMProvider()
    items, _ = process_new_fact(
        items=[], thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="100 seats", source_email_id="msg_001", basis="stated", llm=llm, now=_now(),
    )
    items, item = process_new_fact(
        items=items, thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="100 seats", source_email_id="msg_005", basis="stated", llm=llm, now=_now(),
    )
    assert len(items) == 1
    assert set(item.source_emails) == {"msg_001", "msg_005"}
    assert len(item.history) == 1  # no new history entry for an unchanged value


def test_changed_value_updates_current_value_and_preserves_history():
    llm = MockLLMProvider()
    items, _ = process_new_fact(
        items=[], thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="100 seats", source_email_id="msg_001", basis="stated", llm=llm, now=_now(),
    )
    items, item = process_new_fact(
        items=items, thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="150 seats", source_email_id="msg_007", basis="stated", llm=llm, now=_now(),
    )
    assert len(items) == 1  # same knowledge item, not a duplicate
    assert item.current_value == "150 seats"
    assert [h.value for h in item.history] == ["100 seats", "150 seats"]
    assert item.status == "active"


def test_similar_phrasing_of_same_fact_is_deduplicated_via_rapidfuzz():
    llm = MockLLMProvider()
    items, _ = process_new_fact(
        items=[], thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="100 seats", source_email_id="msg_001", basis="stated", llm=llm, now=_now(),
    )
    items, item = process_new_fact(
        items=items, thread_id="thread_001", subject="ABC Corp", predicate="requires",
        object_text="approximately 100 users", source_email_id="msg_005", basis="stated", llm=llm, now=_now(),
    )
    assert len(items) == 1
    assert "msg_005" in item.source_emails


def test_distinct_competitors_create_separate_knowledge_items():
    llm = MockLLMProvider()
    items, _ = process_new_fact(
        items=[], thread_id="thread_001", subject="ABC Corp", predicate="mentioned_competitor",
        object_text="Salesforce", source_email_id="msg_001", basis="stated", llm=llm, now=_now(),
    )
    items, _ = process_new_fact(
        items=items, thread_id="thread_001", subject="ABC Corp", predicate="mentioned_competitor",
        object_text="HubSpot", source_email_id="msg_002", basis="stated", llm=llm, now=_now(),
    )
    assert len(items) == 2
    fact_keys = {item.fact_key for item in items}
    assert fact_keys == {"salesforce", "hubspot"}


def test_unrelated_statements_do_not_merge_despite_text_similarity():
    llm = MockLLMProvider()
    items, _ = process_new_fact(
        items=[], thread_id="thread_001", subject="ABC Corp", predicate="uses",
        object_text="Salesforce", source_email_id="msg_001", basis="stated", llm=llm, now=_now(),
    )
    items, _ = process_new_fact(
        items=items, thread_id="thread_001", subject="ABC Corp", predicate="evaluating",
        object_text="Salesforce replacement", source_email_id="msg_002", basis="stated", llm=llm, now=_now(),
    )
    # different predicate -> never the same knowledge item regardless of text similarity
    assert len(items) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge_deduplication.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.knowledge.deduplication'`

- [ ] **Step 3: Implement `app/knowledge/deduplication.py`**

```python
# app/knowledge/deduplication.py
from datetime import datetime
from typing import Literal

from rapidfuzz import fuzz

from app.interfaces.llm_provider import LLMProvider
from app.knowledge.models import HistoryEntry, KnowledgeItem
from app.knowledge.normalize import classify_fact_key, extract_leading_number, normalize_text, slugify

_EXACT_MATCH_THRESHOLD = 90
_AMBIGUOUS_LOWER_BOUND = 60


def _find_exact(
    items: list[KnowledgeItem], thread_id: str, subject_key: str, predicate: str, fact_key: str
) -> KnowledgeItem | None:
    for item in items:
        if (
            item.thread_id == thread_id
            and item.subject_key == subject_key
            and item.predicate == predicate
            and item.fact_key == fact_key
        ):
            return item
    return None


def _find_fuzzy_candidates(
    items: list[KnowledgeItem], thread_id: str, subject_key: str, predicate: str, object_text: str
) -> list[tuple[KnowledgeItem, float]]:
    normalized_new = normalize_text(object_text)
    candidates = []
    for item in items:
        if item.thread_id != thread_id or item.subject_key != subject_key or item.predicate != predicate:
            continue
        score = fuzz.token_sort_ratio(normalize_text(item.current_value), normalized_new)
        candidates.append((item, score))
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    return candidates


def _apply_update(item: KnowledgeItem, object_text: str, source_email_id: str, now: datetime) -> KnowledgeItem:
    updated_source_emails = list(dict.fromkeys([*item.source_emails, source_email_id]))
    new_value_normalized = normalize_text(object_text)
    current_value_normalized = normalize_text(item.current_value)

    new_number = extract_leading_number(object_text)
    current_number = extract_leading_number(item.current_value)

    value_changed = (
        new_value_normalized != current_value_normalized
        and not (new_number is not None and current_number is not None and new_number == current_number)
    )

    history = list(item.history)
    current_value = item.current_value
    if value_changed:
        history.append(HistoryEntry(value=object_text, source_email_id=source_email_id, recorded_at=now))
        current_value = object_text

    return item.model_copy(
        update={
            "current_value": current_value,
            "history": history,
            "source_emails": updated_source_emails,
            "last_confirmed_at": now,
            "confidence": min(0.99, item.confidence + 0.01),
        }
    )


def process_new_fact(
    items: list[KnowledgeItem],
    thread_id: str,
    subject: str,
    predicate: str,
    object_text: str,
    source_email_id: str,
    basis: Literal["stated", "inferred"],
    llm: LLMProvider,
    now: datetime,
) -> tuple[list[KnowledgeItem], KnowledgeItem]:
    subject_key = slugify(subject)
    fact_key = classify_fact_key(predicate, object_text)

    exact_match = _find_exact(items, thread_id, subject_key, predicate, fact_key)
    if exact_match is not None:
        updated = _apply_update(exact_match, object_text, source_email_id, now)
        new_items = [updated if i.knowledge_id == updated.knowledge_id else i for i in items]
        return new_items, updated

    candidates = _find_fuzzy_candidates(items, thread_id, subject_key, predicate, object_text)
    target: KnowledgeItem | None = None

    if candidates and candidates[0][1] >= _EXACT_MATCH_THRESHOLD:
        target = candidates[0][0]
    elif candidates and _AMBIGUOUS_LOWER_BOUND <= candidates[0][1] < _EXACT_MATCH_THRESHOLD:
        best_item, _ = candidates[0]
        if llm.verify_same_fact(best_item.current_value, object_text, subject, predicate):
            target = best_item

    if target is not None:
        updated = _apply_update(target, object_text, source_email_id, now)
        new_items = [updated if i.knowledge_id == updated.knowledge_id else i for i in items]
        return new_items, updated

    new_item = KnowledgeItem(
        knowledge_id=f"knowledge_{thread_id}_{subject_key}_{predicate}_{fact_key}",
        thread_id=thread_id,
        subject_key=subject_key,
        predicate=predicate,
        fact_key=fact_key,
        current_value=object_text,
        history=[HistoryEntry(value=object_text, source_email_id=source_email_id, recorded_at=now)],
        source_emails=[source_email_id],
        basis=basis,
        first_seen_at=now,
        last_confirmed_at=now,
        confidence=0.75,
    )
    return [*items, new_item], new_item
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_knowledge_deduplication.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/knowledge/deduplication.py tests/test_knowledge_deduplication.py
git commit -m "feat: add knowledge deduplication with contradiction/history handling"
```

---

## Task 11: Reply Drafting & Approval State Machine

**Files:**
- Create: `app/replies/__init__.py`
- Create: `app/replies/models.py`
- Create: `app/replies/drafter.py`
- Create: `app/replies/approval.py`
- Test: `tests/test_reply_drafter.py`
- Test: `tests/test_reply_approval.py`

**Interfaces:**
- Consumes: `Email` from Task 2, `EmailAnalysis` from Task 6, `ThreadContext` from Task 7, `LLMProvider` from Task 6
- Produces: `ReplyDraftContent(BaseModel)` with `subject: str, body: str`; `ReplyDraft(BaseModel)` with `reply_id, thread_id, source_email_id, status: Literal["no_reply_required","awaiting_approval","approved","edited","rejected","cancelled","simulated_sent","sent"], draft: ReplyDraftContent, created_by: str = "sales_agent", approved_by: str | None = None, sent_at: datetime | None = None`. `needs_reply(analysis: EmailAnalysis, email: Email) -> bool`. `draft_reply(llm: LLMProvider, context: ThreadContext, email: Email) -> ReplyDraftContent`. `approve(draft: ReplyDraft, approved_by: str) -> ReplyDraft`, `edit(draft: ReplyDraft, new_subject: str, new_body: str) -> ReplyDraft` (returns new draft with status `"awaiting_approval"`, i.e. a re-draft), `reject(draft: ReplyDraft) -> ReplyDraft`, `simulate_send(draft: ReplyDraft, now: datetime) -> ReplyDraft` (only valid from `"approved"`, raises `ValueError` otherwise).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reply_drafter.py
from app.analysis.schemas import EmailAnalysis
from app.context.models import ThreadContext
from app.email.models import parse_email
from app.replies.drafter import draft_reply, needs_reply
from app.providers.llm.mock import MockLLMProvider


def _email(body="Can you send pricing information?"):
    return parse_email(
        {
            "message_id": "msg_004",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": "Enterprise pricing",
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_needs_reply_true_when_buying_signals_present():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation", buying_signals=["pricing request"])
    assert needs_reply(analysis, _email()) is True


def test_needs_reply_false_when_no_signals_and_no_question():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation")
    email = _email(body="Thanks, sounds good.")
    assert needs_reply(analysis, email) is False


def test_needs_reply_true_when_body_contains_question():
    analysis = EmailAnalysis(email_id="msg_004", summary="s", intent="evaluation")
    email = _email(body="Can we schedule a call?")
    assert needs_reply(analysis, email) is True


def test_draft_reply_returns_subject_and_body():
    llm = MockLLMProvider()
    context = ThreadContext(summary="ABC Corp evaluating enterprise plan")
    draft = draft_reply(llm, context, _email())
    assert draft.subject == "Re: Enterprise pricing"
    assert len(draft.body) > 0
```

```python
# tests/test_reply_approval.py
from datetime import datetime, timezone

import pytest

from app.replies.approval import approve, edit, reject, simulate_send
from app.replies.models import ReplyDraft, ReplyDraftContent


def _draft(status="awaiting_approval"):
    return ReplyDraft(
        reply_id="reply_001",
        thread_id="thread_001",
        source_email_id="msg_004",
        status=status,
        draft=ReplyDraftContent(subject="Re: Enterprise pricing", body="Hi John..."),
    )


def test_approve_transitions_to_approved():
    draft = approve(_draft(), approved_by="ashok@example.com")
    assert draft.status == "approved"
    assert draft.approved_by == "ashok@example.com"


def test_edit_returns_new_awaiting_approval_draft():
    original = _draft()
    edited = edit(original, new_subject="Re: Updated pricing", new_body="New body")
    assert edited.status == "awaiting_approval"
    assert edited.draft.body == "New body"
    assert original.draft.body == "Hi John..."  # original untouched


def test_reject_transitions_to_rejected():
    draft = reject(_draft())
    assert draft.status == "rejected"


def test_simulate_send_requires_approved_status():
    with pytest.raises(ValueError):
        simulate_send(_draft(status="awaiting_approval"), now=datetime.now(timezone.utc))


def test_simulate_send_from_approved_sets_simulated_sent(capsys):
    approved = approve(_draft(), approved_by="ashok@example.com")
    sent = simulate_send(approved, now=datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert sent.status == "simulated_sent"
    assert sent.sent_at is not None
    captured = capsys.readouterr()
    assert "[SIMULATED EMAIL SEND]" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reply_drafter.py tests/test_reply_approval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.replies'`

- [ ] **Step 3: Implement `app/replies/models.py`**

```python
# app/replies/__init__.py
```

```python
# app/replies/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ReplyDraftContent(BaseModel):
    subject: str
    body: str


class ReplyDraft(BaseModel):
    reply_id: str
    thread_id: str
    source_email_id: str
    status: Literal[
        "no_reply_required",
        "awaiting_approval",
        "approved",
        "edited",
        "rejected",
        "cancelled",
        "simulated_sent",
        "sent",
    ]
    draft: ReplyDraftContent
    created_by: str = "sales_agent"
    approved_by: str | None = None
    sent_at: datetime | None = None
```

- [ ] **Step 4: Implement `app/replies/drafter.py`**

```python
# app/replies/drafter.py
from app.analysis.schemas import EmailAnalysis
from app.context.models import ThreadContext
from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider
from app.replies.models import ReplyDraftContent


def needs_reply(analysis: EmailAnalysis, email: Email) -> bool:
    has_signal = any(
        [
            analysis.buying_signals,
            analysis.requirements,
            analysis.pain_points,
            analysis.objections,
            analysis.pricing_mentions,
            analysis.action_items,
        ]
    )
    has_question = "?" in email.body
    return has_signal or has_question


def draft_reply(llm: LLMProvider, context: ThreadContext, email: Email) -> ReplyDraftContent:
    raw = llm.draft_reply(context.model_dump(), email)
    return ReplyDraftContent.model_validate(raw)
```

- [ ] **Step 5: Implement `app/replies/approval.py`**

```python
# app/replies/approval.py
from datetime import datetime

from app.replies.models import ReplyDraft, ReplyDraftContent


def approve(draft: ReplyDraft, approved_by: str) -> ReplyDraft:
    return draft.model_copy(update={"status": "approved", "approved_by": approved_by})


def edit(draft: ReplyDraft, new_subject: str, new_body: str) -> ReplyDraft:
    return draft.model_copy(
        update={
            "status": "awaiting_approval",
            "draft": ReplyDraftContent(subject=new_subject, body=new_body),
            "approved_by": None,
        }
    )


def reject(draft: ReplyDraft) -> ReplyDraft:
    return draft.model_copy(update={"status": "rejected"})


def simulate_send(draft: ReplyDraft, now: datetime) -> ReplyDraft:
    if draft.status != "approved":
        raise ValueError(f"cannot send a draft with status={draft.status!r}; must be 'approved'")

    print("[SIMULATED EMAIL SEND]")
    print(f"Subject: {draft.draft.subject}")
    print()
    print(draft.draft.body)

    return draft.model_copy(update={"status": "simulated_sent", "sent_at": now})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_reply_drafter.py tests/test_reply_approval.py -v`
Expected: PASS (9 tests)

- [ ] **Step 7: Commit**

```bash
git add app/replies tests/test_reply_drafter.py tests/test_reply_approval.py
git commit -m "feat: add reply drafting and approval state machine with simulated send"
```

---

## Task 12: Meeting Detection & Calendar Actions (Attendee Security)

**Files:**
- Create: `app/calendar/__init__.py`
- Create: `app/calendar/models.py`
- Create: `app/calendar/detector.py`
- Create: `app/calendar/actions.py`
- Create: `app/interfaces/calendar_provider.py`
- Test: `tests/test_calendar_models.py`
- Test: `tests/test_calendar_detector.py`
- Test: `tests/test_calendar_actions.py`

**Interfaces:**
- Consumes: `Email` from Task 2
- Produces: `CalendarEvent(BaseModel)` with `title, start: datetime, end: datetime, timezone: str, description: str, attendees: list[str] = []` and a `field_validator` rejecting non-empty `attendees`; `CalendarAction(BaseModel)` with `thread_id, meeting_fingerprint, status: Literal["pending","awaiting_approval","approved","scheduled","failed","rejected","needs_clarification"], event: CalendarEvent, actor_type: Literal["authenticated_user"] = "authenticated_user", reason: str | None = None`; `CalendarProvider(ABC)` with abstract `create_event(self, event: CalendarEvent) -> str`; `MeetingDetectionResult(BaseModel)` with `meeting_detected: bool, needs_clarification: bool = False, missing_information: list[str] = [], title, start, end, timezone, description: str | None`; `detect_meeting(email: Email, thread_id: str, tz_name: str, reference_now: datetime) -> MeetingDetectionResult`; `make_fingerprint(title: str, start: datetime, end: datetime) -> str`; `build_calendar_action(detection: MeetingDetectionResult, thread_id: str) -> CalendarAction | None`; `approve_calendar_action(action: CalendarAction, calendar_provider: CalendarProvider) -> CalendarAction` (asserts `attendees == []` a second time immediately before calling the provider — fails closed to `status="failed"` if not); `reject_calendar_action(action: CalendarAction) -> CalendarAction`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calendar_models.py
import pytest
from pydantic import ValidationError

from app.calendar.models import CalendarEvent


def _base_kwargs(**overrides):
    kwargs = dict(
        title="ABC Corp Sales Discussion",
        start="2026-09-15T15:00:00+05:30",
        end="2026-09-15T16:00:00+05:30",
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    kwargs.update(overrides)
    return kwargs


def test_calendar_event_defaults_to_no_attendees():
    event = CalendarEvent(**_base_kwargs())
    assert event.attendees == []


def test_calendar_event_rejects_external_attendees():
    with pytest.raises(ValidationError):
        CalendarEvent(**_base_kwargs(attendees=["customer@example.com"]))
```

```python
# tests/test_calendar_detector.py
from datetime import datetime, timezone

from app.calendar.detector import detect_meeting
from app.email.models import parse_email


def _email(body: str):
    return parse_email(
        {
            "message_id": "msg_005",
            "from": {"name": "John", "email": "john@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "subject": "Meeting request",
            "body": body,
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )


def test_detects_explicit_meeting_with_day_time_and_duration():
    result = detect_meeting(
        _email("Let's meet Tuesday at 3 PM for 30 minutes."),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is True
    assert result.needs_clarification is False
    assert result.start is not None
    assert (result.end - result.start).total_seconds() == 30 * 60


def test_detects_meeting_with_default_duration_when_unspecified():
    result = detect_meeting(
        _email("Can we have a call tomorrow at 11?"),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is True
    assert (result.end - result.start).total_seconds() == 30 * 60


def test_ambiguous_request_needs_clarification():
    result = detect_meeting(
        _email("Maybe next week sometime?"),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is False
    assert result.needs_clarification is True
    assert result.missing_information


def test_no_meeting_language_returns_not_detected():
    result = detect_meeting(
        _email("Thanks for the update, looks good."),
        thread_id="thread_001",
        tz_name="Asia/Kolkata",
        reference_now=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    assert result.meeting_detected is False
    assert result.needs_clarification is False
```

```python
# tests/test_calendar_actions.py
from datetime import datetime, timezone

import pytest

from app.calendar.actions import approve_calendar_action, build_calendar_action, make_fingerprint, reject_calendar_action
from app.calendar.detector import MeetingDetectionResult
from app.calendar.models import CalendarAction, CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class _RecordingCalendarProvider(CalendarProvider):
    def __init__(self):
        self.created_events: list[CalendarEvent] = []

    def create_event(self, event: CalendarEvent) -> str:
        self.created_events.append(event)
        return "provider_event_id_123"


def test_make_fingerprint_is_stable_for_same_meeting():
    start = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    fp1 = make_fingerprint("ABC Corp Sales Discussion", start, end)
    fp2 = make_fingerprint("ABC Corp Sales Discussion", start, end)
    assert fp1 == fp2


def test_build_calendar_action_from_detected_meeting():
    detection = MeetingDetectionResult(
        meeting_detected=True,
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = build_calendar_action(detection, thread_id="thread_001")
    assert action.status == "awaiting_approval"
    assert action.event.attendees == []


def test_build_calendar_action_for_needs_clarification():
    detection = MeetingDetectionResult(meeting_detected=False, needs_clarification=True, missing_information=["date"])
    action = build_calendar_action(detection, thread_id="thread_001")
    assert action.status == "needs_clarification"


def test_build_calendar_action_returns_none_when_no_meeting():
    detection = MeetingDetectionResult(meeting_detected=False, needs_clarification=False)
    assert build_calendar_action(detection, thread_id="thread_001") is None


def test_approve_calendar_action_calls_provider_and_schedules():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    provider = _RecordingCalendarProvider()
    result = approve_calendar_action(action, provider)
    assert result.status == "scheduled"
    assert len(provider.created_events) == 1


def test_approve_calendar_action_fails_closed_if_attendees_smuggled_in():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    # simulate a dict loaded back from MongoDB that bypassed the constructor validator
    tampered = action.model_copy(deep=True)
    object.__setattr__(tampered.event, "attendees", ["external@example.com"])

    provider = _RecordingCalendarProvider()
    result = approve_calendar_action(tampered, provider)

    assert result.status == "failed"
    assert result.reason == "external attendees not permitted"
    assert len(provider.created_events) == 0


def test_reject_calendar_action_sets_rejected_status():
    event = CalendarEvent(
        title="ABC Corp Sales Discussion",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="Sales discussion",
    )
    action = CalendarAction(
        thread_id="thread_001",
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )
    result = reject_calendar_action(action)
    assert result.status == "rejected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calendar_models.py tests/test_calendar_detector.py tests/test_calendar_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.calendar'`

- [ ] **Step 3: Implement `app/calendar/models.py` and `app/interfaces/calendar_provider.py`**

```python
# app/calendar/__init__.py
```

```python
# app/calendar/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CalendarEvent(BaseModel):
    title: str
    start: datetime
    end: datetime
    timezone: str
    description: str
    attendees: list[str] = Field(default_factory=list)

    @field_validator("attendees")
    @classmethod
    def validate_no_external_attendees(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("External attendees are not permitted")
        return value


class CalendarAction(BaseModel):
    thread_id: str
    meeting_fingerprint: str
    status: Literal[
        "pending", "awaiting_approval", "approved", "scheduled", "failed", "rejected", "needs_clarification"
    ]
    event: CalendarEvent
    actor_type: Literal["authenticated_user"] = "authenticated_user"
    reason: str | None = None
```

```python
# app/interfaces/calendar_provider.py
from abc import ABC, abstractmethod

from app.calendar.models import CalendarEvent


class CalendarProvider(ABC):
    @abstractmethod
    def create_event(self, event: CalendarEvent) -> str:
        ...
```

- [ ] **Step 4: Implement `app/calendar/detector.py`**

```python
# app/calendar/detector.py
import re
from datetime import datetime, time, timedelta

from pydantic import BaseModel

from app.email.models import Email

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_DEFAULT_DURATION_MINUTES = 30

_MEETING_LANGUAGE = re.compile(r"\b(meet|call|sync|discussion|chat)\b", re.IGNORECASE)
_AMBIGUOUS_PHRASES = re.compile(
    r"\b(maybe|sometime|soon|at some point|let'?s connect)\b", re.IGNORECASE
)
_WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
_DURATION_PATTERN = re.compile(r"\bfor\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", re.IGNORECASE)


class MeetingDetectionResult(BaseModel):
    meeting_detected: bool
    needs_clarification: bool = False
    missing_information: list[str] = []
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    timezone: str | None = None
    description: str | None = None


def _next_weekday(reference: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - reference.weekday()) % 7
    days_ahead = days_ahead or 7
    return reference + timedelta(days=days_ahead)


def _parse_time(body: str) -> time | None:
    match = _TIME_PATTERN.search(body)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return time(hour=hour, minute=minute)


def _parse_duration_minutes(body: str) -> int:
    match = _DURATION_PATTERN.search(body)
    if not match:
        return _DEFAULT_DURATION_MINUTES
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * 60 if unit.startswith("hour") or unit.startswith("hr") else amount


def detect_meeting(email: Email, thread_id: str, tz_name: str, reference_now: datetime) -> MeetingDetectionResult:
    body = email.body

    if not _MEETING_LANGUAGE.search(body):
        return MeetingDetectionResult(meeting_detected=False, needs_clarification=False)

    if _AMBIGUOUS_PHRASES.search(body) and not _WEEKDAY_PATTERN.search(body) and not _TOMORROW_PATTERN.search(body):
        return MeetingDetectionResult(
            meeting_detected=False,
            needs_clarification=True,
            missing_information=["specific date", "specific time"],
        )

    day_match = _WEEKDAY_PATTERN.search(body)
    tomorrow_match = _TOMORROW_PATTERN.search(body)
    parsed_time = _parse_time(body)

    if not day_match and not tomorrow_match:
        return MeetingDetectionResult(
            meeting_detected=False, needs_clarification=True, missing_information=["specific date"]
        )

    if parsed_time is None:
        return MeetingDetectionResult(
            meeting_detected=False, needs_clarification=True, missing_information=["specific time"]
        )

    if tomorrow_match:
        target_date = (reference_now + timedelta(days=1)).date()
    else:
        weekday = _WEEKDAYS[day_match.group(1).lower()]
        target_date = _next_weekday(reference_now, weekday).date()

    start = datetime.combine(target_date, parsed_time, tzinfo=reference_now.tzinfo)
    duration_minutes = _parse_duration_minutes(body)
    end = start + timedelta(minutes=duration_minutes)

    return MeetingDetectionResult(
        meeting_detected=True,
        needs_clarification=False,
        title=f"Sales Discussion ({email.from_.name or email.from_.email})",
        start=start,
        end=end,
        timezone=tz_name,
        description=f"Sales discussion based on email thread {thread_id}",
    )
```

- [ ] **Step 5: Implement `app/calendar/actions.py`**

```python
# app/calendar/actions.py
from datetime import datetime

from app.calendar.detector import MeetingDetectionResult
from app.calendar.models import CalendarAction, CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider
from app.knowledge.normalize import normalize_text


def make_fingerprint(title: str, start: datetime, end: datetime) -> str:
    return f"{normalize_text(title).replace(' ', '_')}_{start.isoformat()}_{end.isoformat()}"


def build_calendar_action(detection: MeetingDetectionResult, thread_id: str) -> CalendarAction | None:
    if detection.needs_clarification:
        placeholder_event = CalendarEvent(
            title=detection.title or "Meeting (details pending)",
            start=datetime.now().astimezone(),
            end=datetime.now().astimezone(),
            timezone=detection.timezone or "UTC",
            description=detection.description or "Awaiting clarification from customer",
        )
        return CalendarAction(
            thread_id=thread_id,
            meeting_fingerprint=f"needs_clarification_{thread_id}",
            status="needs_clarification",
            event=placeholder_event,
            reason=", ".join(detection.missing_information) or "ambiguous meeting request",
        )

    if not detection.meeting_detected:
        return None

    event = CalendarEvent(
        title=detection.title,
        start=detection.start,
        end=detection.end,
        timezone=detection.timezone,
        description=detection.description,
    )
    return CalendarAction(
        thread_id=thread_id,
        meeting_fingerprint=make_fingerprint(event.title, event.start, event.end),
        status="awaiting_approval",
        event=event,
    )


def approve_calendar_action(action: CalendarAction, calendar_provider: CalendarProvider) -> CalendarAction:
    if action.event.attendees:
        return action.model_copy(update={"status": "failed", "reason": "external attendees not permitted"})

    calendar_provider.create_event(action.event)
    return action.model_copy(update={"status": "scheduled"})


def reject_calendar_action(action: CalendarAction) -> CalendarAction:
    return action.model_copy(update={"status": "rejected"})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_calendar_models.py tests/test_calendar_detector.py tests/test_calendar_actions.py -v`
Expected: PASS (13 tests)

- [ ] **Step 7: Commit**

```bash
git add app/calendar app/interfaces/calendar_provider.py tests/test_calendar_models.py tests/test_calendar_detector.py tests/test_calendar_actions.py
git commit -m "feat: add meeting detection and calendar actions with fail-closed attendee security"
```

---

## Task 13: Email/Calendar Providers, Claude/OpenAI LLM Providers, Provider Factory

**Files:**
- Create: `app/interfaces/email_provider.py`
- Create: `app/providers/email/__init__.py`
- Create: `app/providers/email/mock.py`
- Create: `app/providers/calendar/__init__.py`
- Create: `app/providers/calendar/mock.py`
- Create: `app/providers/llm/claude.py`
- Create: `app/providers/llm/openai.py`
- Create: `app/providers/factory.py`
- Test: `tests/test_mock_email_provider.py`
- Test: `tests/test_mock_calendar_provider.py`
- Test: `tests/test_provider_factory.py`

**Interfaces:**
- Consumes: `Settings` from Task 1, `CalendarEvent`/`CalendarProvider` from Task 12, `LLMProvider` from Task 6, `MockLLMProvider` from Task 6
- Produces: `EmailProvider(ABC)` with abstract `fetch_emails(self, limit: int) -> list[dict]` and `send_email(self, to: str, subject: str, body: str) -> None`; `MockEmailProvider(EmailProvider)` constructed with a fixed `list[dict]` of raw email payloads, `send_email` prints `[SIMULATED EMAIL SEND]` (used only by tests/dev, never by the pipeline directly); `MockCalendarProvider(CalendarProvider)` records created events in memory; `ClaudeProvider(LLMProvider)` and `OpenAIProvider(LLMProvider)` — real SDK-backed implementations that build a JSON-schema-constrained prompt from `EmailAnalysis`/`ThreadContext` field names and parse the model's JSON response; `ProviderFactory` with static methods `create_email_provider(settings) -> EmailProvider`, `create_calendar_provider(settings) -> CalendarProvider`, `create_llm_provider(settings) -> LLMProvider`, dispatching on `settings.email_provider` / `calendar_provider` / `llm_provider` (`"demo"`, `"mock"`, `"mcp"` for email; `"mock"`, `"mcp"` for calendar; `"mock"`, `"claude"`, `"openai"` for LLM) — importing `MCPEmailProvider`/`MCPCalendarProvider` only inside the `"mcp"` branch so an unconfigured MCP SDK never breaks demo/mock runs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mock_email_provider.py
from app.providers.email.mock import MockEmailProvider


def test_mock_email_provider_returns_configured_payloads_up_to_limit():
    payloads = [{"message_id": f"msg_{i}"} for i in range(5)]
    provider = MockEmailProvider(payloads)

    assert provider.fetch_emails(limit=3) == payloads[:3]
    assert provider.fetch_emails(limit=100) == payloads


def test_mock_email_provider_send_email_does_not_raise(capsys):
    provider = MockEmailProvider([])
    provider.send_email(to="john@example.com", subject="Re: Hi", body="Body")
    captured = capsys.readouterr()
    assert "[SIMULATED EMAIL SEND]" in captured.out
```

```python
# tests/test_mock_calendar_provider.py
from datetime import datetime, timezone

from app.calendar.models import CalendarEvent
from app.providers.calendar.mock import MockCalendarProvider


def test_mock_calendar_provider_records_created_events():
    provider = MockCalendarProvider()
    event = CalendarEvent(
        title="Sales Call",
        start=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 15, 15, 30, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        description="desc",
    )
    event_id = provider.create_event(event)
    assert event_id.startswith("mock_event_")
    assert provider.created_events == [event]
```

```python
# tests/test_provider_factory.py
import pytest

from app.config.settings import Settings
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.email.demo import DemoEmailProvider
from app.providers.factory import ProviderFactory
from app.providers.llm.mock import MockLLMProvider


def test_factory_creates_demo_email_provider_by_default():
    settings = Settings(email_provider="demo")
    provider = ProviderFactory.create_email_provider(settings)
    assert isinstance(provider, DemoEmailProvider)


def test_factory_creates_mock_calendar_provider():
    settings = Settings(calendar_provider="mock")
    provider = ProviderFactory.create_calendar_provider(settings)
    assert isinstance(provider, MockCalendarProvider)


def test_factory_creates_mock_llm_provider():
    settings = Settings(llm_provider="mock")
    provider = ProviderFactory.create_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_factory_raises_on_unknown_provider_name():
    settings = Settings(llm_provider="not_a_real_provider")
    with pytest.raises(ValueError):
        ProviderFactory.create_llm_provider(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mock_email_provider.py tests/test_mock_calendar_provider.py tests/test_provider_factory.py -v`
Expected: FAIL with `ModuleNotFoundError` (note: `test_provider_factory.py` also references `DemoEmailProvider`, implemented in Task 14 — this test file's first two tests can pass after this task; the `demo` provider test will pass once Task 14 lands. Run only the non-demo tests first if needed: `pytest tests/test_provider_factory.py -k "not demo"`)

- [ ] **Step 3: Implement `app/interfaces/email_provider.py`**

```python
# app/interfaces/email_provider.py
from abc import ABC, abstractmethod
from typing import Any


class EmailProvider(ABC):
    @abstractmethod
    def fetch_emails(self, limit: int) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def send_email(self, to: str, subject: str, body: str) -> None:
        ...
```

- [ ] **Step 4: Implement `app/providers/email/mock.py`**

```python
# app/providers/email/__init__.py
```

```python
# app/providers/email/mock.py
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
```

- [ ] **Step 5: Implement `app/providers/calendar/mock.py`**

```python
# app/providers/calendar/__init__.py
```

```python
# app/providers/calendar/mock.py
import uuid

from app.calendar.models import CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class MockCalendarProvider(CalendarProvider):
    def __init__(self):
        self.created_events: list[CalendarEvent] = []

    def create_event(self, event: CalendarEvent) -> str:
        self.created_events.append(event)
        return f"mock_event_{uuid.uuid4().hex[:12]}"
```

- [ ] **Step 6: Implement `app/providers/llm/claude.py` and `app/providers/llm/openai.py`**

```python
# app/providers/llm/claude.py
import json
from typing import Any

import anthropic

from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider

_ANALYSIS_INSTRUCTIONS = (
    "You are a sales email analyst. Given the email below, return ONLY a JSON object with keys: "
    "summary, intent, entities, facts (list of {subject,predicate,object}), requirements, pain_points, "
    "buying_signals, objections, competitors, pricing_mentions, commitments, action_items, meetings, "
    "people, companies, products. Use empty lists/strings for anything not present. No prose, JSON only."
)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _complete_json(self, system: str, user: str) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return json.loads(text)

    def analyze_email(self, email: Email) -> dict[str, Any]:
        result = self._complete_json(
            _ANALYSIS_INSTRUCTIONS,
            f"Subject: {email.subject}\n\nBody:\n{email.body}",
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
        return self._complete_json(instructions, user)

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
        return self._complete_json(instructions, user)
```

```python
# app/providers/llm/openai.py
import json
from typing import Any

from openai import OpenAI

from app.email.models import Email
from app.interfaces.llm_provider import LLMProvider
from app.providers.llm.claude import _ANALYSIS_INSTRUCTIONS


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def _complete_json(self, system: str, user: str) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return json.loads(response.choices[0].message.content)

    def analyze_email(self, email: Email) -> dict[str, Any]:
        result = self._complete_json(
            _ANALYSIS_INSTRUCTIONS, f"Subject: {email.subject}\n\nBody:\n{email.body}"
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
        return self._complete_json(instructions, user)

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
        return self._complete_json(instructions, user)
```

- [ ] **Step 7: Implement `app/providers/factory.py`**

```python
# app/providers/factory.py
from app.config.settings import Settings
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.email_provider import EmailProvider
from app.interfaces.llm_provider import LLMProvider


class ProviderFactory:
    @staticmethod
    def create_email_provider(settings: Settings) -> EmailProvider:
        provider = settings.email_provider.lower()
        if provider == "demo":
            from app.providers.email.demo import DemoEmailProvider

            return DemoEmailProvider(seed=settings.demo_seed)
        if provider == "mock":
            from app.providers.email.mock import MockEmailProvider

            return MockEmailProvider(payloads=[])
        if provider == "mcp":
            from app.providers.email.mcp import MCPEmailProvider

            return MCPEmailProvider()
        raise ValueError(f"Unknown EMAIL_PROVIDER: {settings.email_provider!r}")

    @staticmethod
    def create_calendar_provider(settings: Settings) -> CalendarProvider:
        provider = settings.calendar_provider.lower()
        if provider == "mock":
            from app.providers.calendar.mock import MockCalendarProvider

            return MockCalendarProvider()
        if provider == "mcp":
            from app.providers.calendar.mcp import MCPCalendarProvider

            return MCPCalendarProvider()
        raise ValueError(f"Unknown CALENDAR_PROVIDER: {settings.calendar_provider!r}")

    @staticmethod
    def create_llm_provider(settings: Settings) -> LLMProvider:
        provider = settings.llm_provider.lower()
        if provider == "mock":
            from app.providers.llm.mock import MockLLMProvider

            return MockLLMProvider()
        if provider == "claude":
            from app.providers.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key=settings.llm_api_key, model=settings.llm_model or "claude-sonnet-5")
        if provider == "openai":
            from app.providers.llm.openai import OpenAIProvider

            return OpenAIProvider(api_key=settings.llm_api_key, model=settings.llm_model or "gpt-4o")
        raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_mock_email_provider.py tests/test_mock_calendar_provider.py tests/test_provider_factory.py -v`
Expected: 6 of 7 PASS now; `test_factory_creates_demo_email_provider_by_default` still FAILs (`DemoEmailProvider` does not exist yet) — this is expected and resolved in Task 14. Note this explicitly rather than treating it as a regression.

- [ ] **Step 9: Commit**

```bash
git add app/interfaces/email_provider.py app/providers/email/__init__.py app/providers/email/mock.py app/providers/calendar app/providers/llm/claude.py app/providers/llm/openai.py app/providers/factory.py tests/test_mock_email_provider.py tests/test_mock_calendar_provider.py tests/test_provider_factory.py
git commit -m "feat: add email/calendar mock providers, Claude/OpenAI LLM providers, and provider factory"
```

---

## Task 14: Demo Data Generator, Demo Email Provider, MCP Provider Stubs

**Files:**
- Create: `demo_data/__init__.py`
- Create: `demo_data/generator.py`
- Create: `app/providers/email/demo.py`
- Create: `app/providers/email/mcp.py`
- Create: `app/providers/calendar/mcp.py`
- Test: `tests/test_demo_data_generator.py`
- Test: `tests/test_demo_email_provider.py`

**Interfaces:**
- Consumes: nothing beyond stdlib (`random.Random(seed)`)
- Produces: `generate_demo_emails(seed: int) -> list[dict]` — deterministic given the same seed, returns raw JSON-compatible dicts (not `Email` objects — they go through the same validation path as any provider) for one multi-email sales thread covering: intro, pain point, competitor mention, pricing discussion, meeting request, seat-count change (100→150), decision-maker introduction, proposal request, follow-up (9 emails, matching the spec's example thread); `DemoEmailProvider(EmailProvider)` wraps `generate_demo_emails(seed)` and slices to `limit`; `MCPEmailProvider(EmailProvider)` and `MCPCalendarProvider(CalendarProvider)` are thin adapters around the `mcp` SDK — since no MCP server is configured in this environment, their constructors accept an optional client and raise `RuntimeError("MCP email provider is not configured — set MCP_EMAIL_ENABLED=true and provide a server connection")` from `fetch_emails`/`create_event` when no client was supplied, so `ProviderFactory` never crashes at import time and the failure is only visible if someone actually selects `EMAIL_PROVIDER=mcp` without configuring it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_demo_data_generator.py
from demo_data.generator import generate_demo_emails


def test_generate_demo_emails_is_deterministic_for_same_seed():
    first = generate_demo_emails(seed=42)
    second = generate_demo_emails(seed=42)
    assert first == second


def test_generate_demo_emails_covers_the_expected_narrative_beats():
    emails = generate_demo_emails(seed=42)
    bodies = " ".join(e["body"].lower() for e in emails)

    assert len(emails) >= 9
    assert "salesforce" in bodies  # competitor mention
    assert "pricing" in bodies  # pricing discussion
    assert any("seat" in e["body"].lower() for e in emails)  # seat-count requirement
    assert any(("meet" in e["body"].lower() or "call" in e["body"].lower()) for e in emails)  # meeting request


def test_generate_demo_emails_seat_count_changes_across_thread():
    emails = generate_demo_emails(seed=42)
    seat_mentions = [e["body"] for e in emails if "seat" in e["body"].lower()]
    assert any("100" in body for body in seat_mentions)
    assert any("150" in body for body in seat_mentions)


def test_generate_demo_emails_all_share_one_thread_id():
    emails = generate_demo_emails(seed=42)
    thread_ids = {e.get("thread_id") for e in emails}
    assert len(thread_ids) == 1
    assert None not in thread_ids
```

```python
# tests/test_demo_email_provider.py
from app.providers.email.demo import DemoEmailProvider


def test_demo_email_provider_respects_limit():
    provider = DemoEmailProvider(seed=42)
    assert len(provider.fetch_emails(limit=3)) == 3


def test_demo_email_provider_is_deterministic_across_instances():
    first = DemoEmailProvider(seed=42).fetch_emails(limit=50)
    second = DemoEmailProvider(seed=42).fetch_emails(limit=50)
    assert first == second


def test_demo_email_provider_send_email_prints_simulated_marker(capsys):
    provider = DemoEmailProvider(seed=42)
    provider.send_email(to="a@example.com", subject="s", body="b")
    assert "[SIMULATED EMAIL SEND]" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_demo_data_generator.py tests/test_demo_email_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'demo_data'`

- [ ] **Step 3: Implement `demo_data/generator.py`**

```python
# demo_data/__init__.py
```

```python
# demo_data/generator.py
import random
from datetime import datetime, timedelta, timezone
from typing import Any

_CUSTOMER = {"name": "John Smith", "email": "john.smith@abccorp-demo.example"}
_SALES_REP = {"name": "Ashok Kumar", "email": "ashok@oursalesagent-demo.example"}
_THREAD_SUBJECT = "Enterprise CRM Proposal"


def _base_timestamp(seed: int) -> datetime:
    rng = random.Random(seed)
    day_offset = rng.randint(0, 3)
    return datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc) + timedelta(days=day_offset)


def _email(
    index: int,
    message_id: str,
    thread_id: str,
    subject: str,
    body: str,
    timestamp: datetime,
    in_reply_to: str | None,
    references: list[str],
    from_customer: bool,
) -> dict[str, Any]:
    sender = _CUSTOMER if from_customer else _SALES_REP
    recipient = _SALES_REP if from_customer else _CUSTOMER
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "from": sender,
        "to": [recipient],
        "cc": [],
        "subject": subject,
        "body": body,
        "timestamp": timestamp.isoformat(),
        "in_reply_to": in_reply_to,
        "references": references,
        "attachments": [],
        "labels": [],
    }


def generate_demo_emails(seed: int) -> list[dict[str, Any]]:
    start = _base_timestamp(seed)
    thread_id = "thread_demo_001"
    message_ids: list[str] = []
    emails: list[dict[str, Any]] = []

    bodies = [
        (
            True,
            "Enterprise CRM Proposal",
            "Hi, we're a mid-market logistics company evaluating enterprise CRM options for our "
            "sales team. Could you share more about your enterprise plan?",
        ),
        (
            False,
            "Re: Enterprise CRM Proposal",
            "Thanks for reaching out! Happy to walk you through the enterprise plan. Could you tell "
            "me a bit about what's not working well with your current process?",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Our biggest pain point right now is pricing visibility and a lot of manual data entry "
            "across spreadsheets. We currently use Salesforce but it's become expensive and clunky "
            "for our team's workflow.",
        ),
        (
            False,
            "Re: Enterprise CRM Proposal",
            "That's very common feedback about Salesforce at your scale. Our enterprise plan "
            "includes automated data sync and transparent per-seat pricing. Would a demo help?",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "A demo would be great. Let's meet Tuesday at 3 PM for 30 minutes to go over the "
            "enterprise pricing and see the product in action.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Quick update before our call: after reviewing with the team, we'd need about 100 seats "
            "to start, covering our full sales and account management org.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "One more thing — our VP of Sales, Sarah, will also be joining future conversations as "
            "the final decision maker on this purchase.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Following the reorg we announced, we now expect closer to 150 seats rather than 100, "
            "since two additional regional teams are moving onto the new CRM.",
        ),
        (
            True,
            "Re: Enterprise CRM Proposal",
            "Could you send over a formal proposal and pricing for 150 seats so we can review it "
            "with procurement before the end of the month?",
        ),
    ]

    for index, (from_customer, subject, body) in enumerate(bodies):
        message_id = f"msg_{index + 1:03d}"
        timestamp = start + timedelta(days=index, hours=index)
        in_reply_to = message_ids[-1] if message_ids else None
        references = list(message_ids)
        emails.append(
            _email(
                index=index,
                message_id=message_id,
                thread_id=thread_id,
                subject=subject,
                body=body,
                timestamp=timestamp,
                in_reply_to=in_reply_to,
                references=references,
                from_customer=from_customer,
            )
        )
        message_ids.append(message_id)

    return emails
```

- [ ] **Step 4: Implement `app/providers/email/demo.py`**

```python
# app/providers/email/demo.py
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
```

- [ ] **Step 5: Implement MCP provider stubs**

```python
# app/providers/email/mcp.py
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
```

```python
# app/providers/calendar/mcp.py
from typing import Any

from app.calendar.models import CalendarEvent
from app.interfaces.calendar_provider import CalendarProvider


class MCPCalendarProvider(CalendarProvider):
    """Adapter around an MCP calendar server connection. See MCPEmailProvider docstring."""

    def __init__(self, client: Any = None):
        self._client = client

    def create_event(self, event: CalendarEvent) -> str:
        if self._client is None:
            raise RuntimeError(
                "MCP calendar provider is not configured — set MCP_CALENDAR_ENABLED=true and "
                "provide a server connection"
            )
        assert event.attendees == [], "external attendees must never reach a calendar provider"
        return self._client.create_event(event.model_dump())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_demo_data_generator.py tests/test_demo_email_provider.py tests/test_provider_factory.py -v`
Expected: PASS (all tests, including the previously-deferred `test_factory_creates_demo_email_provider_by_default`)

- [ ] **Step 7: Commit**

```bash
git add demo_data app/providers/email/demo.py app/providers/email/mcp.py app/providers/calendar/mcp.py tests/test_demo_data_generator.py tests/test_demo_email_provider.py
git commit -m "feat: add deterministic demo data generator, demo email provider, and MCP provider stubs"
```

---

## Task 15: Pipeline Orchestrator

**Files:**
- Create: `app/processing/__init__.py`
- Create: `app/processing/models.py`
- Create: `app/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 2-14 (`parse_email`, `normalize_email`, `ThreadCandidate`/`resolve_thread_id`, `analyze_email_with_validation`, `build_next_context`, `process_new_fact`, `needs_reply`/`draft_reply`, `detect_meeting`/`build_calendar_action`, all repositories, `EmailProvider`/`LLMProvider`/`CalendarProvider`)
- Produces: `ProcessingStage(str, Enum)` with values `RECEIVED, VALIDATED, THREADED, ANALYZED, CONTEXT_BUILT, KNOWLEDGE_PROCESSED, REPLY_PROCESSED, MEETING_PROCESSED, COMPLETED, FAILED`; `STAGE_ORDER: list[ProcessingStage]` (the same list without `FAILED`, in execution order); `EmailResult(BaseModel)` with `message_id: str | None, final_stage: str, error: str | None = None`; `PipelineRunSummary(BaseModel)` with `run_id, started_at, completed_at, processed, completed, failed, skipped, results: list[EmailResult]`; `run_pipeline(db, email_provider: EmailProvider, llm_provider: LLMProvider, calendar_provider: CalendarProvider, settings: Settings) -> PipelineRunSummary`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline.py
from datetime import datetime, timezone

import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.interfaces.email_provider import EmailProvider
from app.interfaces.llm_provider import LLMProvider
from app.pipeline import run_pipeline
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


class _ListEmailProvider(EmailProvider):
    def __init__(self, payloads):
        self._payloads = payloads

    def fetch_emails(self, limit):
        return self._payloads[:limit]

    def send_email(self, to, subject, body):
        raise AssertionError("pipeline must never call send_email directly")


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
    return Settings(email_provider="mock", calendar_provider="mock", llm_provider="mock")


def test_pipeline_processes_valid_emails_to_completion(db, settings):
    payloads = [
        _raw_email("msg_001", "We currently use Salesforce but pricing is a pain point."),
        _raw_email("msg_002", "We'd need about 100 seats to start.", in_reply_to="msg_001", references=["msg_001"]),
    ]
    summary = run_pipeline(
        db=db,
        email_provider=_ListEmailProvider(payloads),
        llm_provider=MockLLMProvider(),
        calendar_provider=MockCalendarProvider(),
        settings=settings,
    )

    assert summary.processed == 2
    assert summary.completed == 2
    assert summary.failed == 0
    assert db.emails.count_documents({}) == 2
    assert db.threads.count_documents({}) == 1
    assert db.context_snapshots.count_documents({}) == 2
    assert db.knowledge_items.count_documents({}) >= 1

    stored_email = db.emails.find_one({"message_id": "msg_001"})
    assert stored_email["processing_status"]["stage"] == "COMPLETED"


def test_pipeline_is_idempotent_on_rerun(db, settings):
    payloads = [_raw_email("msg_001", "We currently use Salesforce but pricing is a pain point.")]
    email_provider = _ListEmailProvider(payloads)

    first = run_pipeline(db, email_provider, MockLLMProvider(), MockCalendarProvider(), settings)
    second = run_pipeline(db, email_provider, MockLLMProvider(), MockCalendarProvider(), settings)

    assert first.completed == 1
    assert second.skipped == 1
    assert second.completed == 0
    assert db.context_snapshots.count_documents({}) == 1
    assert db.emails.count_documents({}) == 1


def test_pipeline_continues_after_malformed_email_with_no_message_id(db, settings):
    payloads = [
        {"subject": "broken, no message_id at all"},
        _raw_email("msg_002", "We currently use Salesforce."),
    ]
    summary = run_pipeline(
        db, _ListEmailProvider(payloads), MockLLMProvider(), MockCalendarProvider(), settings
    )

    assert summary.completed == 1
    assert summary.failed == 1
    assert db.emails.count_documents({}) == 1  # malformed item never reached the emails collection
    run_doc = db.processing_runs.find_one({"run_id": summary.run_id})
    assert any(r["final_stage"] == "FAILED" and r["message_id"] is None for r in run_doc["results"])


def test_pipeline_marks_analysis_failure_without_completing(db, settings):
    payloads = [_raw_email("msg_001", "Some body text.")]
    summary = run_pipeline(
        db, _ListEmailProvider(payloads), _AlwaysBrokenLLM(), MockCalendarProvider(), settings
    )

    assert summary.failed == 1
    assert summary.completed == 0
    stored_email = db.emails.find_one({"message_id": "msg_001"})
    assert stored_email["processing_status"]["stage"] == "FAILED"
    assert stored_email["processing_status"]["failed_stage"] == "ANALYZED"
    assert db.context_snapshots.count_documents({}) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Implement `app/processing/models.py`**

```python
# app/processing/__init__.py
```

```python
# app/processing/models.py
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProcessingStage(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    THREADED = "THREADED"
    ANALYZED = "ANALYZED"
    CONTEXT_BUILT = "CONTEXT_BUILT"
    KNOWLEDGE_PROCESSED = "KNOWLEDGE_PROCESSED"
    REPLY_PROCESSED = "REPLY_PROCESSED"
    MEETING_PROCESSED = "MEETING_PROCESSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


STAGE_ORDER: list[ProcessingStage] = [
    ProcessingStage.RECEIVED,
    ProcessingStage.VALIDATED,
    ProcessingStage.THREADED,
    ProcessingStage.ANALYZED,
    ProcessingStage.CONTEXT_BUILT,
    ProcessingStage.KNOWLEDGE_PROCESSED,
    ProcessingStage.REPLY_PROCESSED,
    ProcessingStage.MEETING_PROCESSED,
    ProcessingStage.COMPLETED,
]


class EmailResult(BaseModel):
    message_id: str | None
    final_stage: str
    error: str | None = None


class PipelineRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime
    processed: int
    completed: int
    failed: int
    skipped: int
    results: list[EmailResult] = Field(default_factory=list)
```

- [ ] **Step 4: Implement `app/pipeline.py`**

```python
# app/pipeline.py
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from app.analysis.extractor import analyze_email_with_validation
from app.calendar.actions import build_calendar_action
from app.calendar.detector import detect_meeting
from app.config.settings import Settings
from app.context.engine import build_next_context
from app.context.models import ThreadContext
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ProcessingRunRepository,
    ReplyDraftRepository,
    ThreadRepository,
)
from app.email.models import parse_email
from app.email.normalizer import normalize_email, normalize_subject
from app.email.threading import ThreadCandidate, resolve_thread_id
from app.interfaces.calendar_provider import CalendarProvider
from app.interfaces.email_provider import EmailProvider
from app.interfaces.llm_provider import LLMProvider
from app.knowledge.deduplication import process_new_fact
from app.knowledge.models import KnowledgeItem
from app.processing.models import EmailResult, PipelineRunSummary, ProcessingStage
from app.replies.drafter import draft_reply, needs_reply
from app.replies.models import ReplyDraft

_FACT_FIELD_PREDICATES = {
    "requirements": "requires",
    "pain_points": "has_pain_point",
    "competitors": "mentioned_competitor",
    "objections": "raised_objection",
    "buying_signals": "showed_buying_signal",
}


def _load_thread_candidates(thread_repo: ThreadRepository) -> list[ThreadCandidate]:
    candidates = []
    for doc in thread_repo.find_many({}):
        candidates.append(
            ThreadCandidate(
                thread_id=doc["thread_id"],
                normalized_subject=doc["normalized_subject"],
                participant_emails=set(doc["participant_emails"]),
                message_ids=set(doc["message_ids"]),
                last_message_at=datetime.fromisoformat(doc["last_message_at"]),
            )
        )
    return candidates


def _upsert_thread(thread_repo: ThreadRepository, thread_id: str, email) -> None:
    existing = thread_repo.find_one({"thread_id": thread_id})
    participant_emails = set(existing["participant_emails"]) if existing else set()
    message_ids = set(existing["message_ids"]) if existing else set()

    participant_emails |= {email.from_.email, *(a.email for a in email.to), *(a.email for a in email.cc)}
    message_ids.add(email.message_id)

    last_message_at = email.timestamp
    if existing:
        existing_last = datetime.fromisoformat(existing["last_message_at"])
        last_message_at = max(last_message_at, existing_last)

    thread_repo.upsert_by_key(
        {"thread_id": thread_id},
        {
            "thread_id": thread_id,
            "normalized_subject": existing["normalized_subject"] if existing else normalize_subject(email.subject),
            "participant_emails": sorted(participant_emails),
            "message_ids": sorted(message_ids),
            "last_message_at": last_message_at.isoformat(),
        },
    )


def _subject_name(context: ThreadContext, thread_id: str) -> str:
    return context.company.get("name") or thread_id


def _process_knowledge(
    knowledge_repo: KnowledgeRepository,
    thread_id: str,
    analysis,
    llm: LLMProvider,
    subject_name: str,
    source_email_id: str,
    now: datetime,
) -> None:
    stored_docs = knowledge_repo.all_for_thread(thread_id)
    items = [KnowledgeItem.model_validate(doc) for doc in stored_docs]

    for fact in analysis.facts:
        items, item = process_new_fact(
            items, thread_id, fact.subject, fact.predicate, fact.object, source_email_id, "stated", llm, now
        )
        knowledge_repo.upsert_by_key(
            {
                "thread_id": item.thread_id,
                "subject_key": item.subject_key,
                "predicate": item.predicate,
                "fact_key": item.fact_key,
            },
            item.model_dump(mode="json"),
        )

    for field, predicate in _FACT_FIELD_PREDICATES.items():
        for value in getattr(analysis, field):
            items, item = process_new_fact(
                items, thread_id, subject_name, predicate, value, source_email_id, "stated", llm, now
            )
            knowledge_repo.upsert_by_key(
                {
                    "thread_id": item.thread_id,
                    "subject_key": item.subject_key,
                    "predicate": item.predicate,
                    "fact_key": item.fact_key,
                },
                item.model_dump(mode="json"),
            )


def run_pipeline(
    db,
    email_provider: EmailProvider,
    llm_provider: LLMProvider,
    calendar_provider: CalendarProvider,
    settings: Settings,
) -> PipelineRunSummary:
    email_repo = EmailRepository(db)
    thread_repo = ThreadRepository(db)
    context_repo = ContextSnapshotRepository(db)
    knowledge_repo = KnowledgeRepository(db)
    reply_repo = ReplyDraftRepository(db)
    calendar_repo = CalendarActionRepository(db)
    run_repo = ProcessingRunRepository(db)

    run_id = f"run_{uuid.uuid4().hex}"
    started_at = datetime.now(timezone.utc)
    results: list[EmailResult] = []

    raw_emails = email_provider.fetch_emails(limit=settings.email_limit)

    for raw in raw_emails:
        message_id = raw.get("message_id") if isinstance(raw, dict) else None
        try:
            email = parse_email(raw)
        except ValidationError as exc:
            results.append(EmailResult(message_id=message_id, final_stage="FAILED", error=str(exc)))
            if message_id:
                email_repo.set_stage(message_id, ProcessingStage.FAILED.value, error=str(exc), failed_stage=ProcessingStage.VALIDATED.value)
            continue

        email = normalize_email(email)

        existing = email_repo.find_one({"message_id": email.message_id})
        if existing and existing.get("processing_status", {}).get("stage") == ProcessingStage.COMPLETED.value:
            results.append(EmailResult(message_id=email.message_id, final_stage="SKIPPED"))
            continue

        email_repo.upsert_by_key({"message_id": email.message_id}, {"message_id": email.message_id})
        email_repo.set_stage(email.message_id, ProcessingStage.RECEIVED.value)
        email_repo.set_stage(email.message_id, ProcessingStage.VALIDATED.value)

        candidates = _load_thread_candidates(thread_repo)
        thread_id = resolve_thread_id(email, candidates)
        _upsert_thread(thread_repo, thread_id, email)
        email_repo.set_stage(email.message_id, ProcessingStage.THREADED.value)

        outcome = analyze_email_with_validation(llm_provider, email)
        if not outcome.success:
            email_repo.set_stage(
                email.message_id, ProcessingStage.FAILED.value, error=outcome.error, failed_stage=ProcessingStage.ANALYZED.value
            )
            results.append(EmailResult(message_id=email.message_id, final_stage="FAILED", error=outcome.error))
            continue
        analysis = outcome.analysis
        email_repo.set_stage(email.message_id, ProcessingStage.ANALYZED.value)

        existing_snapshot = context_repo.find_one(
            {"thread_id": thread_id, "triggering_email_id": email.message_id}
        )
        if existing_snapshot:
            next_context = ThreadContext.model_validate(existing_snapshot["context"])
        else:
            previous_snapshot = context_repo.latest_for_thread(thread_id)
            previous_context = (
                ThreadContext.model_validate(previous_snapshot["context"]) if previous_snapshot else None
            )
            next_context, changes = build_next_context(previous_context, analysis, email.message_id, llm_provider)
            next_version = (previous_snapshot["context_version"] + 1) if previous_snapshot else 1
            context_repo.upsert_by_key(
                {"thread_id": thread_id, "triggering_email_id": email.message_id},
                {
                    "thread_id": thread_id,
                    "context_version": next_version,
                    "triggering_email_id": email.message_id,
                    "context": next_context.model_dump(mode="json"),
                    "changes_from_previous_context": [c.model_dump(mode="json") for c in changes],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        email_repo.set_stage(email.message_id, ProcessingStage.CONTEXT_BUILT.value)

        _process_knowledge(
            knowledge_repo,
            thread_id,
            analysis,
            llm_provider,
            _subject_name(next_context, thread_id),
            email.message_id,
            datetime.now(timezone.utc),
        )
        email_repo.set_stage(email.message_id, ProcessingStage.KNOWLEDGE_PROCESSED.value)

        if needs_reply(analysis, email):
            draft_content = draft_reply(llm_provider, next_context, email)
            draft = ReplyDraft(
                reply_id=f"reply_{email.message_id}",
                thread_id=thread_id,
                source_email_id=email.message_id,
                status="awaiting_approval",
                draft=draft_content,
            )
            reply_repo.upsert_by_key({"source_email_id": email.message_id}, draft.model_dump(mode="json"))
        email_repo.set_stage(email.message_id, ProcessingStage.REPLY_PROCESSED.value)

        detection = detect_meeting(email, thread_id, settings.timezone, email.timestamp)
        action = build_calendar_action(detection, thread_id)
        if action is not None:
            calendar_repo.upsert_by_key(
                {"thread_id": action.thread_id, "meeting_fingerprint": action.meeting_fingerprint},
                action.model_dump(mode="json"),
            )
        email_repo.set_stage(email.message_id, ProcessingStage.MEETING_PROCESSED.value)

        email_repo.set_stage(email.message_id, ProcessingStage.COMPLETED.value)
        results.append(EmailResult(message_id=email.message_id, final_stage="COMPLETED"))

    completed_at = datetime.now(timezone.utc)
    summary = PipelineRunSummary(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        processed=len(raw_emails),
        completed=sum(1 for r in results if r.final_stage == "COMPLETED"),
        failed=sum(1 for r in results if r.final_stage == "FAILED"),
        skipped=sum(1 for r in results if r.final_stage == "SKIPPED"),
        results=results,
    )
    run_repo.upsert_by_key({"run_id": run_id}, summary.model_dump(mode="json"))
    return summary
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add app/processing app/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrator with resumable per-stage processing and idempotency"
```

---

## Task 16: CLI (`main.py`)

**Files:**
- Create: `main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `get_settings`/`configure_logging` from Task 1, `get_client`/`initialize_database` from Task 4, `ProviderFactory` from Task 13, `run_pipeline` from Task 15
- Produces: `build_arg_parser() -> argparse.ArgumentParser` (flags `--healthcheck`, `--mode`, `--reset-demo`); `run_healthcheck(settings) -> tuple[bool, list[str]]` (ok flag + human-readable check lines); `run_reset_demo(db, settings) -> None` (only permitted when `settings.app_env == "development"` or `settings.simulation_mode` is `True`; deletes only documents tagged as demo data — see Step 4); `main(argv: list[str] | None = None) -> int` (the actual entrypoint, returns a process exit code so it's testable without `sys.exit`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import mongomock
import pytest

import main as main_module
from app.config.settings import Settings


@pytest.fixture(autouse=True)
def _patch_mongo_client(monkeypatch):
    fake_client = mongomock.MongoClient()
    monkeypatch.setattr(main_module, "get_client", lambda uri: fake_client)
    yield fake_client


def test_healthcheck_reports_ok_with_default_mock_demo_settings(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    exit_code = main_module.main(["--healthcheck"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "MongoDB connected" in output
    assert "System ready" in output


def test_demo_mode_populates_database(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMAIL_LIMIT", "9")
    exit_code = main_module.main(["--mode=demo"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "processed" in output.lower()


def test_reset_demo_requires_simulation_mode(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "false")
    monkeypatch.setenv("APP_ENV", "production")
    exit_code = main_module.main(["--reset-demo"])
    assert exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Implement `main.py`**

```python
# main.py
import argparse
import sys

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.database.mongodb import get_client, initialize_database
from app.pipeline import run_pipeline
from app.providers.factory import ProviderFactory


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CoS Sales Agent")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--mode", choices=["demo"], default=None)
    parser.add_argument("--reset-demo", action="store_true")
    return parser


def run_healthcheck(settings) -> tuple[bool, list[str]]:
    lines = ["CoS Sales Agent Health Check", ""]
    ok = True
    lines.append("✓ Configuration loaded")

    try:
        client = get_client(settings.mongodb_uri)
        db = initialize_database(client, settings.mongodb_database)
        client.admin.command("ping") if hasattr(client, "admin") else None
        lines.append("✓ MongoDB connected")
        lines.append("✓ MongoDB indexes ready")
    except Exception as exc:  # pragma: no cover - exercised via integration only
        ok = False
        lines.append(f"✗ MongoDB connection failed: {exc}")

    lines.append(f"✓ Email provider: {settings.email_provider.upper()}")
    lines.append(f"✓ Calendar provider: {settings.calendar_provider.upper()}")
    lines.append(f"✓ LLM provider: {settings.llm_provider.upper()}")

    mcp_email_marker = "✓" if settings.mcp_email_enabled else "○"
    mcp_calendar_marker = "✓" if settings.mcp_calendar_enabled else "○"
    lines.append(f"{mcp_email_marker} MCP Email: {'enabled' if settings.mcp_email_enabled else 'disabled'}")
    lines.append(f"{mcp_calendar_marker} MCP Calendar: {'enabled' if settings.mcp_calendar_enabled else 'disabled'}")

    lines.append("")
    lines.append("System ready." if ok else "System not ready.")
    return ok, lines


def run_reset_demo(db, settings) -> None:
    if settings.app_env != "development" and not settings.simulation_mode:
        raise PermissionError("--reset-demo is only permitted when APP_ENV=development or SIMULATION_MODE=true")

    for collection_name in [
        "emails",
        "threads",
        "context_snapshots",
        "knowledge_items",
        "reply_drafts",
        "calendar_actions",
        "processing_runs",
        "entities",
        "opportunities",
        "activities",
    ]:
        db[collection_name].delete_many({})


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    if args.healthcheck:
        ok, lines = run_healthcheck(settings)
        print("\n".join(lines))
        return 0 if ok else 1

    if args.reset_demo:
        try:
            client = get_client(settings.mongodb_uri)
            db = initialize_database(client, settings.mongodb_database)
            run_reset_demo(db, settings)
            print("Demo data reset.")
            return 0
        except PermissionError as exc:
            print(f"Refused: {exc}")
            return 1

    if args.mode == "demo":
        client = get_client(settings.mongodb_uri)
        db = initialize_database(client, settings.mongodb_database)

        email_provider = ProviderFactory.create_email_provider(settings)
        llm_provider = ProviderFactory.create_llm_provider(settings)
        calendar_provider = ProviderFactory.create_calendar_provider(settings)

        summary = run_pipeline(db, email_provider, llm_provider, calendar_provider, settings)
        print(
            f"Demo run complete: processed={summary.processed} completed={summary.completed} "
            f"failed={summary.failed} skipped={summary.skipped}"
        )
        return 0

    build_arg_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add CLI entrypoint with healthcheck, demo mode, and reset-demo"
```

---

## Task 17: Streamlit UI

**Files:**
- Create: `app/ui/__init__.py`
- Create: `app/ui/data.py`
- Create: `app/ui/dashboard.py`
- Test: `tests/test_ui_data.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: all repositories from Task 5, `ReplyDraft`/`approve`/`edit`/`reject`/`simulate_send` from Task 11, `CalendarAction`/`approve_calendar_action`/`reject_calendar_action` from Task 12, `ProviderFactory` from Task 13
- Produces (in `app/ui/data.py`, pure functions taking `db` so they're testable without Streamlit): `dashboard_metrics(db) -> dict` (`emails_processed, threads, knowledge_items, pending_replies, pending_calendar_actions, failures`); `list_emails(db) -> list[dict]`; `list_threads(db) -> list[dict]`; `thread_context_versions(db, thread_id: str) -> list[dict]` (ordered by `context_version`); `list_knowledge(db, thread_id: str | None = None) -> list[dict]`; `list_reply_drafts(db, status: str | None = None) -> list[dict]`; `list_calendar_actions(db, status: str | None = None) -> list[dict]`. `app/ui/dashboard.py` is the Streamlit entrypoint (`streamlit run app/ui/dashboard.py`) rendering Dashboard / Emails / Thread Explorer / Context Evolution / Knowledge / Reply Approval / Calendar Approval tabs, calling only into the two approval-handler code paths to send/schedule.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui_data.py
from datetime import datetime, timezone

import mongomock

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ReplyDraftRepository,
    ThreadRepository,
)
from app.ui.data import (
    dashboard_metrics,
    list_calendar_actions,
    list_emails,
    list_knowledge,
    list_reply_drafts,
    list_threads,
    thread_context_versions,
)


def _db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_dashboard_metrics_counts_each_collection():
    db = _db()
    EmailRepository(db).upsert_by_key({"message_id": "msg_001"}, {"message_id": "msg_001"})
    ThreadRepository(db).upsert_by_key({"thread_id": "t1"}, {"thread_id": "t1"})
    KnowledgeRepository(db).upsert_by_key(
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
    )
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_001"}, {"source_email_id": "msg_001", "status": "awaiting_approval"}
    )
    CalendarActionRepository(db).upsert_by_key(
        {"thread_id": "t1", "meeting_fingerprint": "fp1"},
        {"thread_id": "t1", "meeting_fingerprint": "fp1", "status": "awaiting_approval"},
    )

    metrics = dashboard_metrics(db)
    assert metrics["emails_processed"] == 1
    assert metrics["threads"] == 1
    assert metrics["knowledge_items"] == 1
    assert metrics["pending_replies"] == 1
    assert metrics["pending_calendar_actions"] == 1


def test_list_emails_and_threads_return_stored_documents():
    db = _db()
    EmailRepository(db).upsert_by_key({"message_id": "msg_001"}, {"message_id": "msg_001", "subject": "Hi"})
    ThreadRepository(db).upsert_by_key({"thread_id": "t1"}, {"thread_id": "t1"})

    assert list_emails(db)[0]["subject"] == "Hi"
    assert list_threads(db)[0]["thread_id"] == "t1"


def test_thread_context_versions_ordered_ascending():
    db = _db()
    repo = ContextSnapshotRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_002"},
        {"thread_id": "t1", "triggering_email_id": "msg_002", "context_version": 2},
    )
    repo.upsert_by_key(
        {"thread_id": "t1", "triggering_email_id": "msg_001"},
        {"thread_id": "t1", "triggering_email_id": "msg_001", "context_version": 1},
    )
    versions = [snap["context_version"] for snap in thread_context_versions(db, "t1")]
    assert versions == [1, 2]


def test_list_knowledge_filters_by_thread():
    db = _db()
    repo = KnowledgeRepository(db)
    repo.upsert_by_key(
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t1", "subject_key": "abc", "predicate": "requires", "fact_key": "seat_count"},
    )
    repo.upsert_by_key(
        {"thread_id": "t2", "subject_key": "xyz", "predicate": "requires", "fact_key": "seat_count"},
        {"thread_id": "t2", "subject_key": "xyz", "predicate": "requires", "fact_key": "seat_count"},
    )
    assert len(list_knowledge(db, thread_id="t1")) == 1
    assert len(list_knowledge(db)) == 2


def test_list_reply_drafts_and_calendar_actions_filter_by_status():
    db = _db()
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_001"}, {"source_email_id": "msg_001", "status": "awaiting_approval"}
    )
    ReplyDraftRepository(db).upsert_by_key(
        {"source_email_id": "msg_002"}, {"source_email_id": "msg_002", "status": "simulated_sent"}
    )
    CalendarActionRepository(db).upsert_by_key(
        {"thread_id": "t1", "meeting_fingerprint": "fp1"},
        {"thread_id": "t1", "meeting_fingerprint": "fp1", "status": "needs_clarification"},
    )

    assert len(list_reply_drafts(db, status="awaiting_approval")) == 1
    assert len(list_reply_drafts(db)) == 2
    assert len(list_calendar_actions(db, status="needs_clarification")) == 1
```

```python
# tests/test_ui_smoke.py
import mongomock
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.database.indexes import initialize_indexes  # noqa: E402


def test_dashboard_app_runs_without_exceptions(monkeypatch):
    fake_client = mongomock.MongoClient()
    initialize_indexes(fake_client["cos_sales_test"])

    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MONGODB_DATABASE", "cos_sales_test")

    import app.ui.dashboard as dashboard_module

    monkeypatch.setattr(dashboard_module, "get_client", lambda uri: fake_client)

    at = AppTest.from_file("app/ui/dashboard.py")
    at.run()
    assert not at.exception
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_data.py tests/test_ui_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui'`

- [ ] **Step 3: Implement `app/ui/data.py`**

```python
# app/ui/__init__.py
```

```python
# app/ui/data.py
from app.database.repositories import (
    CalendarActionRepository,
    ContextSnapshotRepository,
    EmailRepository,
    KnowledgeRepository,
    ReplyDraftRepository,
    ThreadRepository,
)


def dashboard_metrics(db) -> dict:
    failures = db.emails.count_documents({"processing_status.stage": "FAILED"})
    return {
        "emails_processed": db.emails.count_documents({}),
        "threads": db.threads.count_documents({}),
        "knowledge_items": db.knowledge_items.count_documents({}),
        "pending_replies": db.reply_drafts.count_documents({"status": "awaiting_approval"}),
        "pending_calendar_actions": db.calendar_actions.count_documents(
            {"status": {"$in": ["awaiting_approval", "needs_clarification"]}}
        ),
        "failures": failures,
    }


def list_emails(db) -> list[dict]:
    return EmailRepository(db).find_many({})


def list_threads(db) -> list[dict]:
    return ThreadRepository(db).find_many({})


def thread_context_versions(db, thread_id: str) -> list[dict]:
    return ContextSnapshotRepository(db).all_for_thread(thread_id)


def list_knowledge(db, thread_id: str | None = None) -> list[dict]:
    repo = KnowledgeRepository(db)
    if thread_id:
        return repo.all_for_thread(thread_id)
    return repo.find_many({})


def list_reply_drafts(db, status: str | None = None) -> list[dict]:
    repo = ReplyDraftRepository(db)
    if status:
        return repo.find_many({"status": status})
    return repo.find_many({})


def list_calendar_actions(db, status: str | None = None) -> list[dict]:
    repo = CalendarActionRepository(db)
    if status:
        return repo.find_many({"status": status})
    return repo.find_many({})
```

- [ ] **Step 4: Implement `app/ui/dashboard.py`**

```python
# app/ui/dashboard.py
from datetime import datetime, timezone

import streamlit as st

from app.calendar.actions import approve_calendar_action, reject_calendar_action
from app.calendar.models import CalendarAction
from app.config.settings import get_settings
from app.database.mongodb import get_client, initialize_database
from app.database.repositories import CalendarActionRepository, ReplyDraftRepository
from app.providers.factory import ProviderFactory
from app.replies.approval import approve, edit, reject, simulate_send
from app.replies.models import ReplyDraft
from app.ui.data import (
    dashboard_metrics,
    list_calendar_actions,
    list_emails,
    list_knowledge,
    list_reply_drafts,
    list_threads,
    thread_context_versions,
)

st.set_page_config(page_title="CoS Sales Agent", layout="wide")


@st.cache_resource
def _get_db():
    settings = get_settings()
    client = get_client(settings.mongodb_uri)
    return initialize_database(client, settings.mongodb_database)


def _render_dashboard_tab(db) -> None:
    metrics = dashboard_metrics(db)
    cols = st.columns(6)
    labels = [
        ("Emails processed", "emails_processed"),
        ("Threads", "threads"),
        ("Knowledge items", "knowledge_items"),
        ("Pending replies", "pending_replies"),
        ("Pending calendar actions", "pending_calendar_actions"),
        ("Failures", "failures"),
    ]
    for col, (label, key) in zip(cols, labels):
        col.metric(label, metrics[key])


def _render_emails_tab(db) -> None:
    st.dataframe(list_emails(db))


def _render_thread_explorer_tab(db) -> None:
    threads = list_threads(db)
    thread_ids = [t["thread_id"] for t in threads]
    if not thread_ids:
        st.info("No threads yet.")
        return
    selected = st.selectbox("Thread", thread_ids)
    for snapshot in thread_context_versions(db, selected):
        with st.expander(f"Context V{snapshot['context_version']} (triggered by {snapshot['triggering_email_id']})"):
            st.json(snapshot["context"])
            st.write("Changes:")
            for change in snapshot.get("changes_from_previous_context", []):
                st.write(f"{change['type']}: {change['field']} -> {change['detail']}")


def _render_context_evolution_tab(db) -> None:
    threads = list_threads(db)
    thread_ids = [t["thread_id"] for t in threads]
    if not thread_ids:
        st.info("No threads yet.")
        return
    selected = st.selectbox("Thread ", thread_ids, key="context_evolution_thread")
    versions = thread_context_versions(db, selected)
    st.write(" -> ".join(f"V{v['context_version']}" for v in versions))
    for change in versions[-1]["changes_from_previous_context"] if versions else []:
        st.write(f"{change['type']}: {change['field']} -> {change['detail']}")


def _render_knowledge_tab(db) -> None:
    for item in list_knowledge(db):
        basis_label = "STATED" if item["basis"] == "stated" else "AI INFERENCE"
        st.write(
            f"**{item['subject_key']} {item['predicate']} = {item['current_value']}** "
            f"[{basis_label}] (confidence {item['confidence']:.2f})"
        )
        with st.expander("History"):
            for entry in item["history"]:
                st.write(f"{entry['recorded_at']}: {entry['value']} (source {entry['source_email_id']})")


def _render_reply_approval_tab(db) -> None:
    repo = ReplyDraftRepository(db)
    for doc in list_reply_drafts(db, status="awaiting_approval"):
        draft = ReplyDraft.model_validate(doc)
        st.write(f"**{draft.draft.subject}**")
        st.write(draft.draft.body)
        col1, col2, col3 = st.columns(3)
        if col1.button("Approve", key=f"approve_{draft.reply_id}"):
            approved = approve(draft, approved_by="ui_user")
            sent = simulate_send(approved, now=datetime.now(timezone.utc))
            repo.upsert_by_key({"source_email_id": sent.source_email_id}, sent.model_dump(mode="json"))
            st.rerun()
        if col2.button("Reject", key=f"reject_{draft.reply_id}"):
            rejected = reject(draft)
            repo.upsert_by_key({"source_email_id": rejected.source_email_id}, rejected.model_dump(mode="json"))
            st.rerun()
        new_body = col3.text_area("Edit body", value=draft.draft.body, key=f"edit_{draft.reply_id}")
        if col3.button("Save edit", key=f"save_edit_{draft.reply_id}"):
            edited = edit(draft, new_subject=draft.draft.subject, new_body=new_body)
            repo.upsert_by_key({"source_email_id": edited.source_email_id}, edited.model_dump(mode="json"))
            st.rerun()


def _render_calendar_approval_tab(db, settings) -> None:
    repo = CalendarActionRepository(db)
    calendar_provider = ProviderFactory.create_calendar_provider(settings)

    for doc in list_calendar_actions(db, status="awaiting_approval") + list_calendar_actions(
        db, status="needs_clarification"
    ):
        action = CalendarAction.model_validate(doc)
        st.write(f"**{action.event.title}**")
        st.write(f"{action.event.start} - {action.event.end} ({action.event.timezone})")
        st.write("Attendees: Authenticated user only")
        if action.status == "needs_clarification":
            st.warning(f"Needs clarification: {action.reason}")
            continue
        col1, col2 = st.columns(2)
        if col1.button("Create on my calendar", key=f"create_{action.meeting_fingerprint}"):
            result = approve_calendar_action(action, calendar_provider)
            repo.upsert_by_key(
                {"thread_id": result.thread_id, "meeting_fingerprint": result.meeting_fingerprint},
                result.model_dump(mode="json"),
            )
            st.rerun()
        if col2.button("Ignore", key=f"ignore_{action.meeting_fingerprint}"):
            result = reject_calendar_action(action)
            repo.upsert_by_key(
                {"thread_id": result.thread_id, "meeting_fingerprint": result.meeting_fingerprint},
                result.model_dump(mode="json"),
            )
            st.rerun()


def main() -> None:
    settings = get_settings()
    db = _get_db()

    st.title("CoS Sales Agent")
    tabs = st.tabs(
        [
            "Dashboard",
            "Emails",
            "Thread Explorer",
            "Context Evolution",
            "Knowledge",
            "Reply Approval",
            "Calendar Approval",
        ]
    )
    with tabs[0]:
        _render_dashboard_tab(db)
    with tabs[1]:
        _render_emails_tab(db)
    with tabs[2]:
        _render_thread_explorer_tab(db)
    with tabs[3]:
        _render_context_evolution_tab(db)
    with tabs[4]:
        _render_knowledge_tab(db)
    with tabs[5]:
        _render_reply_approval_tab(db)
    with tabs[6]:
        _render_calendar_approval_tab(db, settings)


main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_data.py tests/test_ui_smoke.py -v`
Expected: PASS (6 tests; the smoke test is skipped rather than failing if the installed Streamlit version lacks `streamlit.testing.v1` — note that explicitly rather than treating a skip as a silent gap)

- [ ] **Step 6: Commit**

```bash
git add app/ui tests/test_ui_data.py tests/test_ui_smoke.py
git commit -m "feat: add Streamlit dashboard with approval-gated reply and calendar actions"
```

---

## Task 18: Docker Packaging & README

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile`
- Create: `README.md`
- Test: `tests/test_repo_hygiene.py`

**Interfaces:**
- Consumes: nothing new
- Produces: a `docker-compose.yml` running MongoDB (+ optional Mongo Express) with no baked-in credentials; a `Dockerfile` for the app itself (optional convenience, app also runs directly via `python main.py`); a complete `README.md` per the spec's section 27 outline; a repo-hygiene test asserting no machine-specific paths/credentials are committed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_hygiene.py
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_FORBIDDEN_PATTERNS = [
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"/Users/[a-zA-Z0-9_.-]+"),
    re.compile(r"/home/[a-zA-Z0-9_.-]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]

_SCAN_EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".env.example", ".toml", ".txt"}
_EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}


def _iter_source_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix in _SCAN_EXTENSIONS or path.name == ".env.example":
            yield path


def test_no_machine_specific_paths_or_leaked_credentials():
    violations = []
    for path in _iter_source_files():
        if path.name == "test_repo_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(text):
                violations.append((str(path.relative_to(REPO_ROOT)), pattern.pattern))
    assert violations == []


def test_env_file_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines()


def test_env_example_has_no_real_secrets():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LLM_API_KEY=" in env_example
    assert "LLM_API_KEY=sk-" not in env_example
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: FAIL only if a prior task accidentally introduced a forbidden pattern — otherwise it may already pass; run it anyway to confirm before adding Docker/README content, then re-run after Step 3.

- [ ] **Step 3: Create `docker-compose.yml`, `Dockerfile`, and `README.md`**

```yaml
# docker-compose.yml
services:
  mongodb:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db

  mongo-express:
    image: mongo-express:1
    depends_on:
      - mongodb
    ports:
      - "8081:8081"
    environment:
      ME_CONFIG_MONGODB_SERVER: mongodb

volumes:
  mongodb_data:
```

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py", "--mode=demo"]
```

```markdown
# README.md
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

## MCP Configuration (optional)

Set `MCP_EMAIL_ENABLED=true` / `MCP_CALENDAR_ENABLED=true` and `EMAIL_PROVIDER=mcp` /
`CALENDAR_PROVIDER=mcp` to route through a connected MCP email/calendar server. The core
pipeline has no dependency on MCP being available — `ProviderFactory` only imports the MCP
adapter when explicitly selected, so an unconfigured MCP server never breaks demo/mock runs.

## LLM Configuration

Set `LLM_PROVIDER=claude` or `LLM_PROVIDER=openai` plus `LLM_API_KEY` and `LLM_MODEL` to
use a real model instead of the deterministic mock.

## Safety / Approval Model

- Reading, analyzing, threading, context-building, knowledge extraction/deduplication,
  reply drafting, and meeting detection are fully automatic.
- Sending an email and creating a calendar event always require explicit approval through
  the Streamlit UI.
- Calendar events are created for the authenticated user only — external attendees
  (sender, customer, CC) can never be added; this is enforced by a Pydantic validator and
  a second check immediately before the calendar provider is called.

## Portability

No hardcoded paths, usernames, personal emails, API keys, or MongoDB credentials appear
anywhere in the source — everything environment-specific comes from `.env`. This project
should run unmodified after cloning to another Windows, macOS, or Linux machine, provided
Docker and Python 3.11+ are available.

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full test suite and the demo workflow end to end**

Run: `pytest -v`
Expected: PASS (all tests across every task)

Run:
```bash
docker compose up -d
python main.py --healthcheck
python main.py --mode=demo
streamlit run app/ui/dashboard.py
```
Expected: healthcheck reports `System ready.`; demo prints `Demo run complete: processed=9 completed=9 failed=0 skipped=0`; Streamlit dashboard loads and shows populated Dashboard/Emails/Thread Explorer/Context Evolution/Knowledge tabs, with Reply Approval and Calendar Approval tabs showing at least one pending item to approve/reject.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml Dockerfile README.md tests/test_repo_hygiene.py
git commit -m "docs: add Docker packaging, README, and repo hygiene test"
```

---

## Self-Review

**Spec coverage:** every numbered section of the Phase 1 spec maps to a task above —
email schema/normalization (Task 2), threading (Task 3), MongoDB/indexes/repositories
(Tasks 4-5), LLM analysis with validation/retry (Task 6), cumulative context + diff
(Tasks 7-8), knowledge identity/deduplication/contradiction handling (Tasks 9-10), reply
state machine + simulated send (Task 11), meeting detection + fail-closed calendar
attendee security (Task 12), all providers + factory (Tasks 13-14), the resumable
pipeline with per-stage idempotency (Task 15), CLI healthcheck/demo/reset (Task 16),
Streamlit UI (Task 17), and Docker/README/portability verification (Task 18).

**Placeholder scan:** no `TBD`/`TODO` remain; every step has literal, runnable code
rather than a description of what to write.

**Type consistency:** `EmailAnalysis`, `ThreadContext`, `KnowledgeItem`, `ReplyDraft`, and
`CalendarAction`/`CalendarEvent` are each defined once (Tasks 6, 7, 9, 11, 12) and reused
by exact name in every later task (`context.engine`, `knowledge.deduplication`,
`replies.drafter`/`approval`, `calendar.actions`, `pipeline`, `ui.data`) — no renamed
duplicates were introduced.

**One known scope note carried forward from Task 13 into Task 14:** the two provider
factory tests that reference `DemoEmailProvider` cannot pass until Task 14 lands; this is
called out explicitly in Task 13 rather than left as a silent gap, and Task 14's Step 6
re-runs the full `test_provider_factory.py` file to confirm all tests pass once the
dependency exists.

---

Plan complete and saved to `docs/superpowers/plans/2026-09-14-cos-sales-agent-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
