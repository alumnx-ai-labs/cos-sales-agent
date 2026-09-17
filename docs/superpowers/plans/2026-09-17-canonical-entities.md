# Canonical Entity Extraction & Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a canonical entity layer (People, Projects, Commitments, FollowUps, Meetings, PersonalItems) resolved deterministically from an extended LLM analysis, cross-referenced onto every processed email, without changing existing pipeline behavior for anything else.

**Architecture:** A new `app/entities/` package holds Pydantic models, deterministic extraction (regex/date-phrase parsing), and deterministic resolution logic. `EmailAnalysis` gains new optional fields populated by the existing single LLM call (no new API call). A new pipeline stage (`ENTITIES_PROCESSED`, inserted between knowledge processing and reply drafting) resolves mentions to canonical IDs and writes `entities_referenced`/classification metadata back onto the email document.

**Tech Stack:** Existing stack only (Pydantic v2, pymongo, mongomock, rapidfuzz not needed for this feature — every resolution rule here is exact-match, no fuzzy tier).

**Spec:** `docs/superpowers/specs/2026-09-17-canonical-entities-design.md`

## Global Constraints

- The six canonical entity types and only these six: Person (`PER-`), Project (`PRJ-`), Commitment (`COM-`), FollowUp (`FU-`), Meeting (`MTG-`), PersonalItem (`PSN-`). No seventh "Record" entity.
- `record_id` is an alias of `message_id` — same value, no independent generation.
- `counters` collection is infrastructure only, never exposed through any tool.
- The LLM never emits or decides a canonical ID — only descriptive signals. All ID assignment/matching is deterministic Python in `app/entities/resolution.py`.
- Person: exact email match only merges. No email, or no match → always create new with `review_flag=true`. Never merge on name similarity alone.
- Project: exact normalized name + same `entity` + same `goal_pillar` → merge. `entity` alone is never sufficient. No fuzzy tier, no `review_flag` on Project (not in its spec'd field list).
- Commitment/Meeting/PersonalItem: exact natural-key match only (thread + normalized text + date, or sender + normalized description) — compared in Python against existing records, no new derived field persisted for this.
- FollowUp model is exactly `id, commitment_id, thread_id` — nothing else.
- A `FollowUp` is derived **only** from a resolved `Commitment`. A `Meeting` or `PersonalItem` — actionable or not — never creates a `FollowUp` by itself.
- `Meeting` gains exactly one new field beyond its original spec'd list: `actionable: bool`, set as `not raw_meeting.is_past`. No other new fields on any entity.
- Date-phrase resolution (and a `Commitment`'s `made_on`) uses the email's own `timestamp` as the reference point — never wall-clock `datetime.now()` — matching the existing `detect_meeting`'s pattern.
- `source_link` is only set when `message_id` matches `^[0-9a-f]{16}$`; otherwise `None`.
- No changes to `knowledge_items`/`context_snapshots` logic (`_process_knowledge`/`build_next_context` untouched), `reply_drafts`/`calendar_actions` logic (`needs_reply`/`draft_reply`/`detect_meeting`/`build_calendar_action` untouched), or any existing test's expected behavior.
- Every existing test must still pass after each task.

---

## Task 1: Canonical ID Generation

**Files:**
- Create: `app/entities/__init__.py`
- Create: `app/entities/ids.py`
- Modify: `app/database/repositories.py` (add `CounterRepository`)
- Test: `tests/test_entities_ids.py`

**Interfaces:**
- Consumes: `pymongo.database.Database`
- Produces: `next_id(db: Database, prefix: str) -> str` in `app.entities.ids`, used by every resolution function in Task 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entities_ids.py
import mongomock

from app.entities.ids import next_id


def test_next_id_is_sequential_and_zero_padded():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    assert next_id(db, "PER-") == "PER-001"
    assert next_id(db, "PER-") == "PER-002"


def test_next_id_is_independent_per_prefix():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    assert next_id(db, "PER-") == "PER-001"
    assert next_id(db, "PRJ-") == "PRJ-001"
    assert next_id(db, "PER-") == "PER-002"


def test_next_id_grows_past_three_digits_without_erroring():
    client = mongomock.MongoClient()
    db = client["cos_sales_test"]

    for _ in range(1000):
        result = next_id(db, "COM-")

    assert result == "COM-1000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entities_ids.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.entities'`

- [ ] **Step 3: Implement `CounterRepository` and `next_id`**

```python
# app/entities/__init__.py
```

Add this import near the top of `app/database/repositories.py`, alongside the existing
`from pymongo.collection import Collection` / `from pymongo.database import Database` lines:

```python
from pymongo import ReturnDocument
```

Add this class to `app/database/repositories.py`, after `ActivityRepository`:

```python
class CounterRepository(_BaseRepository):
    collection_name = "counters"

    def increment_and_get(self, prefix: str) -> int:
        doc = self._collection.find_one_and_update(
            {"_id": prefix},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["seq"]
```

```python
# app/entities/ids.py
from pymongo.database import Database

from app.database.repositories import CounterRepository


def next_id(db: Database, prefix: str) -> str:
    seq = CounterRepository(db).increment_and_get(prefix)
    return f"{prefix}{seq:03d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entities_ids.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (every existing test plus the 3 new ones)

- [ ] **Step 6: Commit**

```bash
git add app/entities/__init__.py app/entities/ids.py app/database/repositories.py tests/test_entities_ids.py
git commit -m "feat: add atomic canonical ID generation via counters collection"
```

---

## Task 2: Canonical Entity Models

**Files:**
- Create: `app/entities/models.py`
- Test: `tests/test_entities_models.py`

**Interfaces:**
- Consumes: nothing (pure domain layer, like `app/knowledge/models.py`)
- Produces: `Person`, `Project`, `Commitment`, `FollowUp`, `Meeting`, `PersonalItem` (all `pydantic.BaseModel`) in `app.entities.models`. Task 3's repositories and Task 7's resolution functions import these directly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entities_models.py
import pytest
from pydantic import ValidationError

from app.entities.models import Commitment, FollowUp, Meeting, Person, PersonalItem, Project


def test_person_defaults():
    person = Person(id="PER-001", name="Jane Doe", email="jane@example.com")
    assert person.aliases == []
    assert person.review_flag is False
    assert person.source == "gmail"


def test_project_has_no_review_flag_field():
    project = Project(id="PRJ-001", project="Renewal Q4")
    assert not hasattr(project, "review_flag")


def test_commitment_class_field_uses_class_alias():
    commitment = Commitment.model_validate(
        {
            "id": "COM-001",
            "what": "send updated case study",
            "class": "mine",
            "source_record": "msg_001",
            "made_on": "2026-09-13T10:30:00Z",
        }
    )
    assert commitment.commitment_class == "mine"
    dumped = commitment.model_dump(mode="json", by_alias=True)
    assert dumped["class"] == "mine"
    assert "commitment_class" not in dumped


def test_commitment_constructed_by_python_name_also_works():
    commitment = Commitment(
        id="COM-002",
        what="send pricing",
        commitment_class="theirs",
        source_record="msg_002",
        made_on="2026-09-13T10:30:00Z",
    )
    assert commitment.commitment_class == "theirs"


def test_commitment_rejects_invalid_class():
    with pytest.raises(ValidationError):
        Commitment(
            id="COM-003",
            what="x",
            commitment_class="not_a_real_class",
            source_record="msg_003",
            made_on="2026-09-13T10:30:00Z",
        )


def test_follow_up_requires_exactly_one_link():
    with pytest.raises(ValidationError):
        FollowUp(id="FU-001")  # neither set

    with pytest.raises(ValidationError):
        FollowUp(id="FU-002", commitment_id="COM-001", thread_id="thread_1")  # both set

    ok = FollowUp(id="FU-003", commitment_id="COM-001")
    assert ok.thread_id is None


def test_follow_up_has_no_extra_fields():
    follow_up = FollowUp(id="FU-004", thread_id="thread_1")
    assert follow_up.model_dump(mode="json").keys() == {"id", "commitment_id", "thread_id"}


def test_meeting_defaults():
    meeting = Meeting(id="MTG-001")
    assert meeting.attendees == []
    assert meeting.actions_raised == []
    assert meeting.agenda_written is False
    assert meeting.actionable is False


def test_meeting_actionable_can_be_set_true():
    meeting = Meeting(id="MTG-002", actionable=True)
    assert meeting.actionable is True


def test_personal_item_defaults():
    item = PersonalItem(id="PSN-001", type="reminder", description="renew passport")
    assert item.status == "open"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entities_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.entities.models'`

- [ ] **Step 3: Implement `app/entities/models.py`**

```python
# app/entities/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Person(BaseModel):
    id: str
    name: str
    email: str | None = None
    aliases: list[str] = Field(default_factory=list)
    org: str | None = None
    type: str | None = None
    goal_pillar: str | None = None
    role_in_pillar: str | None = None
    tier: str | None = None
    voice_register: str | None = None
    last_inbound: datetime | None = None
    last_outbound: datetime | None = None
    reports_to: str | None = None
    open_threads: list[str] = Field(default_factory=list)
    note_link: str | None = None
    review_flag: bool = False
    source: str = "gmail"


class Project(BaseModel):
    id: str
    project: str
    cluster: str | None = None
    entity: str | None = None
    goal_pillar: str | None = None
    objective: str | None = None
    target: str | None = None
    status: str | None = None
    owner: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    next_milestone: str | None = None
    due: datetime | None = None
    health: str | None = None
    last_movement: datetime | None = None
    note_link: str | None = None
    source: str = "gmail"


class Commitment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    what: str
    commitment_class: Literal["mine", "owed_to_me", "theirs", "recap"] = Field(alias="class")
    importance: str | None = None
    owed_by: str | None = None
    owed_to: str | None = None
    source_record: str
    made_on: datetime
    committed_date: datetime | None = None
    date_type: Literal["stated", "inferred", "window"] | None = None
    status: str = "open"
    goal_pillar: str | None = None
    project_id: str | None = None


class FollowUp(BaseModel):
    id: str
    commitment_id: str | None = None
    thread_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one_link(self) -> "FollowUp":
        if (self.commitment_id is None) == (self.thread_id is None):
            raise ValueError("exactly one of commitment_id or thread_id must be set")
        return self


class Meeting(BaseModel):
    id: str
    date: datetime | None = None
    attendees: list[str] = Field(default_factory=list)
    project_or_pillar: str | None = None
    minutes_record: str | None = None
    actions_raised: list[str] = Field(default_factory=list)
    next_meeting_date: datetime | None = None
    agenda_target: str | None = None
    actionable: bool = False
    agenda_written: bool = False


class PersonalItem(BaseModel):
    id: str
    type: str
    description: str
    date_or_deadline: datetime | None = None
    status: str = "open"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entities_models.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/entities/models.py tests/test_entities_models.py
git commit -m "feat: add canonical entity models (Person, Project, Commitment, FollowUp, Meeting, PersonalItem)"
```

---

## Task 3: Entity Repositories and Indexes

**Files:**
- Modify: `app/database/repositories.py` (add 6 repository classes)
- Modify: `app/database/indexes.py`
- Test: `tests/test_entities_repositories.py`

**Interfaces:**
- Consumes: `Person`/`Project`/`Commitment`/`FollowUp`/`Meeting`/`PersonalItem` from Task 2
- Produces: `PersonRepository`, `ProjectRepository`, `CommitmentRepository` (+ `all_for_thread`), `FollowUpRepository`, `MeetingRepository` (+ `all_for_thread`), `PersonalItemRepository` in `app.database.repositories`. Task 7's resolution functions call these directly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entities_repositories.py
import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_person_repository_upsert_and_email_uniqueness(db):
    repo = PersonRepository(db)
    repo.upsert_by_key({"id": "PER-001"}, {"id": "PER-001", "name": "Jane", "email": "jane@example.com"})

    with pytest.raises(DuplicateKeyError):
        db.people.insert_one({"id": "PER-002", "name": "Jane Two", "email": "jane@example.com"})


def test_person_repository_allows_multiple_people_with_no_email(db):
    db.people.insert_one({"id": "PER-003", "name": "Unknown One", "email": None})
    db.people.insert_one({"id": "PER-004", "name": "Unknown Two", "email": None})

    assert db.people.count_documents({}) == 2


def test_project_repository_upsert_is_idempotent(db):
    repo = ProjectRepository(db)
    repo.upsert_by_key({"id": "PRJ-001"}, {"id": "PRJ-001", "project": "Renewal"})
    repo.upsert_by_key({"id": "PRJ-001"}, {"id": "PRJ-001", "project": "Renewal", "status": "active"})

    assert db.projects.count_documents({}) == 1
    assert repo.find_one({"id": "PRJ-001"})["status"] == "active"


def test_commitment_repository_all_for_thread(db):
    repo = CommitmentRepository(db)
    repo.upsert_by_key(
        {"id": "COM-001"},
        {"id": "COM-001", "thread_id": "thread_1", "what": "send case study"},
    )
    repo.upsert_by_key(
        {"id": "COM-002"},
        {"id": "COM-002", "thread_id": "thread_2", "what": "unrelated"},
    )

    results = repo.all_for_thread("thread_1")
    assert len(results) == 1
    assert results[0]["id"] == "COM-001"


def test_follow_up_repository_upsert(db):
    repo = FollowUpRepository(db)
    repo.upsert_by_key({"id": "FU-001"}, {"id": "FU-001", "commitment_id": "COM-001", "thread_id": None})
    assert repo.find_one({"id": "FU-001"})["commitment_id"] == "COM-001"


def test_meeting_repository_all_for_thread(db):
    repo = MeetingRepository(db)
    repo.upsert_by_key({"id": "MTG-001"}, {"id": "MTG-001", "thread_id": "thread_1"})
    results = repo.all_for_thread("thread_1")
    assert len(results) == 1


def test_personal_item_repository_upsert(db):
    repo = PersonalItemRepository(db)
    repo.upsert_by_key({"id": "PSN-001"}, {"id": "PSN-001", "type": "reminder", "description": "x"})
    assert db.personal_items.count_documents({}) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entities_repositories.py -v`
Expected: FAIL with `ImportError: cannot import name 'PersonRepository' from 'app.database.repositories'`

- [ ] **Step 3: Implement the repositories and indexes**

Add to `app/database/repositories.py`, after `ActivityRepository` (and after `CounterRepository`
from Task 1):

```python
class PersonRepository(_BaseRepository):
    collection_name = "people"


class ProjectRepository(_BaseRepository):
    collection_name = "projects"


class CommitmentRepository(_BaseRepository):
    collection_name = "commitments"

    def all_for_thread(self, thread_id: str) -> list[dict]:
        return self.find_many({"thread_id": thread_id})


class FollowUpRepository(_BaseRepository):
    collection_name = "follow_ups"


class MeetingRepository(_BaseRepository):
    collection_name = "meetings"

    def all_for_thread(self, thread_id: str) -> list[dict]:
        return self.find_many({"thread_id": thread_id})


class PersonalItemRepository(_BaseRepository):
    collection_name = "personal_items"
```

Add to `app/database/indexes.py`'s `initialize_indexes`, after the existing
`db.processing_runs.create_index("started_at")` line:

```python
    db.people.create_index("id", unique=True)
    db.people.create_index("email", unique=True, sparse=True)

    db.projects.create_index("id", unique=True)

    db.commitments.create_index("id", unique=True)
    db.commitments.create_index("thread_id")

    db.follow_ups.create_index("id", unique=True)
    db.follow_ups.create_index("commitment_id", sparse=True)
    db.follow_ups.create_index("thread_id", sparse=True)

    db.meetings.create_index("id", unique=True)
    db.meetings.create_index("thread_id")

    db.personal_items.create_index("id", unique=True)
```

Note: `CommitmentRepository`/`MeetingRepository`'s `all_for_thread` expects a `thread_id`
field to exist on those documents (set by the resolution functions in Task 7 — not by this
task). This task only adds the repository/index scaffolding.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entities_repositories.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/database/repositories.py app/database/indexes.py tests/test_entities_repositories.py
git commit -m "feat: add repositories and indexes for the canonical entity collections"
```

---

## Task 4: Deterministic Extraction (Emails, Domains, Date Phrases)

**Files:**
- Create: `app/entities/extraction.py`
- Create: `app/entities/dates.py`
- Test: `tests/test_entities_extraction.py`
- Test: `tests/test_entities_dates.py`

**Interfaces:**
- Consumes: `Email`/`EmailAddress` (`app.email.models`)
- Produces: `extract_email_addresses_from_text(text: str) -> list[str]`, `domains_from_emails(emails: list[str]) -> list[str]`, `envelope_people(email: Email) -> list[EmailAddress]` in `app.entities.extraction`; `resolve_date_phrase(phrase: str | None, reference_now: datetime) -> tuple[datetime | None, str | None]` and `find_date_phrase(text: str) -> str | None` in `app.entities.dates`. Task 7's resolution functions and Task 8's pipeline stage call `resolve_date_phrase` directly; Task 5's `MockLLMProvider` calls `find_date_phrase` directly (reusing the same pattern set, per spec §5.1.1, rather than maintaining a second set of date regexes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entities_extraction.py
from app.email.models import parse_email
from app.entities.extraction import domains_from_emails, envelope_people, extract_email_addresses_from_text


def test_extract_email_addresses_from_text_finds_all_and_dedupes_case_insensitively():
    text = "Reach me at Jane@Example.com or jane@example.com, cc bob@other.io."
    assert extract_email_addresses_from_text(text) == ["bob@other.io", "jane@example.com"]


def test_extract_email_addresses_from_text_returns_empty_when_none_present():
    assert extract_email_addresses_from_text("No addresses here.") == []


def test_domains_from_emails():
    assert domains_from_emails(["jane@example.com", "bob@other.io", "jane2@example.com"]) == [
        "example.com",
        "other.io",
    ]


def test_envelope_people_dedupes_by_email_across_from_to_cc():
    email = parse_email(
        {
            "message_id": "msg_001",
            "from": {"name": "Jane", "email": "jane@example.com"},
            "to": [{"name": "Ashok", "email": "ashok@example.com"}],
            "cc": [{"name": "Jane Duplicate", "email": "Jane@Example.com"}],
            "subject": "Hi",
            "body": "Body",
            "timestamp": "2026-09-13T10:30:00Z",
        }
    )

    people = envelope_people(email)

    assert len(people) == 2
    emails = sorted(p.email for p in people)
    assert emails == ["ashok@example.com", "jane@example.com"]
```

```python
# tests/test_entities_dates.py
from datetime import datetime, timezone

from app.entities.dates import resolve_date_phrase

_NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)  # a Sunday


def test_resolve_date_phrase_returns_none_for_no_phrase():
    assert resolve_date_phrase(None, _NOW) == (None, None)
    assert resolve_date_phrase("", _NOW) == (None, None)


def test_resolve_date_phrase_handles_explicit_month_day_as_stated():
    resolved, date_type = resolve_date_phrase("by June 5th", _NOW)
    assert date_type == "stated"
    assert resolved.month == 6
    assert resolved.day == 5
    assert resolved.year == 2027  # June 5 already passed in the reference year, rolls to next year


def test_resolve_date_phrase_handles_tomorrow_as_inferred():
    resolved, date_type = resolve_date_phrase("let's talk tomorrow", _NOW)
    assert date_type == "inferred"
    assert resolved.date() == (_NOW.date().replace(day=_NOW.day + 1))


def test_resolve_date_phrase_handles_weekday_as_inferred():
    resolved, date_type = resolve_date_phrase("can we sync next Friday", _NOW)
    assert date_type == "inferred"
    assert resolved.weekday() == 4  # Friday


def test_resolve_date_phrase_handles_vague_phrase_as_window():
    resolved, date_type = resolve_date_phrase("sometime end of month", _NOW)
    assert resolved is None
    assert date_type == "window"


def test_resolve_date_phrase_falls_back_to_window_for_unrecognized_phrase():
    resolved, date_type = resolve_date_phrase("whenever works", _NOW)
    assert resolved is None
    assert date_type == "window"


def test_resolve_date_phrase_handles_relative_duration_in_weeks_as_inferred():
    # Spec worked example: email dated 2026-09-17, "in 2 weeks" -> 2026-10-01
    reference = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    resolved, date_type = resolve_date_phrase("We will meet in 2 weeks.", reference)
    assert date_type == "inferred"
    assert resolved.date().isoformat() == "2026-10-01"


def test_resolve_date_phrase_handles_relative_duration_in_days_with_digit():
    resolved, date_type = resolve_date_phrase("The meeting is in 10 days.", _NOW)
    assert date_type == "inferred"
    assert resolved == _NOW + timedelta(days=10)


def test_resolve_date_phrase_handles_relative_duration_with_spelled_out_number():
    resolved, date_type = resolve_date_phrase("Let's catch up in two weeks.", _NOW)
    assert date_type == "inferred"
    assert resolved == _NOW + timedelta(days=14)


def test_resolve_date_phrase_recognizes_next_month_explicitly_as_window():
    resolved, date_type = resolve_date_phrase("We should meet sometime next month.", _NOW)
    assert resolved is None
    assert date_type == "window"
```

Add this import at the top of `tests/test_entities_dates.py`, alongside the existing
`from datetime import datetime, timezone` line:

```python
from datetime import timedelta
```

```python
# tests/test_entities_dates.py (additional tests, same file)
from app.entities.dates import find_date_phrase


def test_find_date_phrase_returns_first_recognized_expression():
    # The weekday pattern matches only the weekday word itself, not a preceding "next" --
    # resolve_date_phrase always computes the *next* occurrence of that weekday regardless,
    # so the "next" prefix carries no additional information it needs.
    assert find_date_phrase("We will meet in 2 weeks.") == "in 2 weeks"
    assert find_date_phrase("Let's meet next Friday.") == "Friday"
    assert find_date_phrase("We can meet tomorrow.") == "tomorrow"
    assert find_date_phrase("The meeting is in 10 days.") == "in 10 days"


def test_find_date_phrase_returns_none_when_nothing_recognized():
    assert find_date_phrase("Just checking in, no dates mentioned.") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entities_extraction.py tests/test_entities_dates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.entities.extraction'`

- [ ] **Step 3: Implement `app/entities/extraction.py`**

```python
# app/entities/extraction.py
import re

from app.email.models import Email, EmailAddress

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_email_addresses_from_text(text: str) -> list[str]:
    return sorted({match.lower() for match in _EMAIL_PATTERN.findall(text)})


def domains_from_emails(emails: list[str]) -> list[str]:
    return sorted({e.split("@", 1)[1] for e in emails if "@" in e})


def envelope_people(email: Email) -> list[EmailAddress]:
    seen: dict[str, EmailAddress] = {}
    for address in [email.from_, *email.to, *email.cc]:
        seen.setdefault(address.email.lower(), address)
    return list(seen.values())
```

- [ ] **Step 4: Implement `app/entities/dates.py`**

```python
# app/entities/dates.py
import re
from datetime import datetime, timedelta

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_EXPLICIT_DATE_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RELATIVE_DURATION_PATTERN = re.compile(
    r"\bin\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+(day|days|week|weeks)\b",
    re.IGNORECASE,
)
_VAGUE_WINDOW_PATTERN = re.compile(
    r"\bnext month\b|\bsometime\b|\bend of (?:the )?month\b", re.IGNORECASE
)
_DATE_PHRASE_PATTERNS = [
    _EXPLICIT_DATE_PATTERN,
    _TOMORROW_PATTERN,
    _WEEKDAY_PATTERN,
    _RELATIVE_DURATION_PATTERN,
    _VAGUE_WINDOW_PATTERN,
]


def _next_weekday(reference: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - reference.weekday()) % 7
    days_ahead = days_ahead or 7
    return reference + timedelta(days=days_ahead)


def find_date_phrase(text: str) -> str | None:
    """Return the first recognized date-related substring in text, verbatim, or None.

    Used by MockLLMProvider so the phrase a mention carries and the phrase
    resolve_date_phrase later resolves come from the same pattern set (spec S5.1.1).
    """
    for pattern in _DATE_PHRASE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def resolve_date_phrase(
    phrase: str | None, reference_now: datetime
) -> tuple[datetime | None, str | None]:
    if not phrase:
        return None, None

    explicit_match = _EXPLICIT_DATE_PATTERN.search(phrase)
    if explicit_match:
        month = _MONTHS[explicit_match.group(1).lower()[:3]]
        day = int(explicit_match.group(2))
        year = reference_now.year
        candidate = reference_now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
        if candidate < reference_now:
            candidate = candidate.replace(year=year + 1)
        return candidate, "stated"

    if _TOMORROW_PATTERN.search(phrase):
        return reference_now + timedelta(days=1), "inferred"

    weekday_match = _WEEKDAY_PATTERN.search(phrase)
    if weekday_match:
        weekday = _WEEKDAYS[weekday_match.group(1).lower()]
        return _next_weekday(reference_now, weekday), "inferred"

    duration_match = _RELATIVE_DURATION_PATTERN.search(phrase)
    if duration_match:
        amount_word = duration_match.group(1).lower()
        amount = int(amount_word) if amount_word.isdigit() else _NUMBER_WORDS[amount_word]
        unit = duration_match.group(2).lower()
        days = amount * 7 if unit.startswith("week") else amount
        return reference_now + timedelta(days=days), "inferred"

    return None, "window"
```

Note: `_VAGUE_WINDOW_PATTERN` is checked by `find_date_phrase` (so "next month"/"sometime" is
recognized as *a* date phrase worth extracting) but `resolve_date_phrase` still returns
`(None, "window")` for it via the same final fallback every other unrecognized phrase
already hits — it does not need its own branch inside `resolve_date_phrase` because the
outcome is identical either way; it only needs to be in `_DATE_PHRASE_PATTERNS` so
`find_date_phrase` doesn't skip past it in favor of nothing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_entities_extraction.py tests/test_entities_dates.py -v`
Expected: PASS (16 tests: 4 extraction + 12 dates)

- [ ] **Step 6: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/entities/extraction.py app/entities/dates.py tests/test_entities_extraction.py tests/test_entities_dates.py
git commit -m "feat: add deterministic email/domain extraction and date-phrase resolution"
```

---

## Task 5: Extend `EmailAnalysis` and `MockLLMProvider`

**Files:**
- Modify: `app/analysis/schemas.py`
- Modify: `app/providers/llm/mock.py`
- Test: `tests/test_analysis_schemas.py` (extend)
- Test: `tests/test_mock_llm_provider.py` (extend)

**Interfaces:**
- Consumes: `find_date_phrase` from Task 4's `app.entities.dates`
- Produces: `MentionedPerson`, `MentionedProject`, `RawCommitment`, `RawMeeting`, `RawPersonalItem` (new, in `app.analysis.schemas`); `EmailAnalysis` gains `people_mentioned`, `projects_mentioned`, `commitments_mentioned`, `meetings_mentioned`, `personal_items_mentioned`, `goal_pillar`, `label_applied`, `confidence`. Task 7's resolution functions and Task 8's pipeline stage read these fields off the `EmailAnalysis` object `analyze_email_with_validation` already returns.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analysis_schemas.py`:

```python
def test_email_analysis_entity_signal_defaults():
    analysis = EmailAnalysis(email_id="msg_001", summary="s", intent="evaluation")
    assert analysis.people_mentioned == []
    assert analysis.projects_mentioned == []
    assert analysis.commitments_mentioned == []
    assert analysis.meetings_mentioned == []
    assert analysis.personal_items_mentioned == []
    assert analysis.goal_pillar == ""
    assert analysis.label_applied == "Undecided"
    assert analysis.confidence == 0.0


def test_email_analysis_accepts_raw_commitment_with_class_alias():
    analysis = EmailAnalysis.model_validate(
        {
            "email_id": "msg_001",
            "summary": "s",
            "intent": "evaluation",
            "commitments_mentioned": [
                {"what": "send case study", "class": "mine", "date_phrase": "next Friday"}
            ],
        }
    )
    assert analysis.commitments_mentioned[0].commitment_class == "mine"
```

(`from app.analysis.schemas import EmailAnalysis` is already imported at the top of this
file from Task setup in the original implementation.)

Add to `tests/test_mock_llm_provider.py`:

```python
def test_mock_llm_includes_sender_as_mentioned_person():
    provider = MockLLMProvider()
    email = _email("Just checking in.")
    result = provider.analyze_email(email)
    assert result["people_mentioned"] == [
        {"name": "John", "email": "john@example.com", "org": None, "role_hint": None}
    ]


def test_mock_llm_detects_a_mine_commitment_with_weekday_date_phrase():
    provider = MockLLMProvider()
    email = _email("I will send the proposal on Friday.")
    result = provider.analyze_email(email)
    assert len(result["commitments_mentioned"]) == 1
    commitment = result["commitments_mentioned"][0]
    assert commitment["class"] == "mine"
    assert commitment["date_phrase"] == "Friday"


def test_mock_llm_detects_meeting_language_as_meeting_mentioned():
    provider = MockLLMProvider()
    email = _email("Let's meet on Tuesday to go over pricing.")
    result = provider.analyze_email(email)
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "Tuesday"


def test_mock_llm_classification_fields_are_deterministic():
    provider = MockLLMProvider()
    with_signal = provider.analyze_email(_email("Can you send pricing for the enterprise plan?"))
    without_signal = provider.analyze_email(_email("Just an FYI, no action needed."))

    assert with_signal["goal_pillar"] == "Sales"
    assert with_signal["label_applied"] == "Needs reply: ASAP"
    assert without_signal["label_applied"] == "Read only"
    assert with_signal["confidence"] == 0.8


# --- Relative-date meeting/action detection (spec S5.1.1) ---


def test_mock_llm_detects_relative_duration_meeting_with_no_commitment():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Sounds good. We will meet in 2 weeks."))

    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 2 weeks"
    assert result["meetings_mentioned"][0]["is_past"] is False
    # "we will meet" must NOT also be read as a "mine" commitment.
    assert result["commitments_mentioned"] == []


def test_mock_llm_detects_meet_next_weekday():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Let's meet next Friday."))
    assert result["meetings_mentioned"][0]["date_phrase"] == "Friday"


def test_mock_llm_detects_meet_tomorrow():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("We can meet tomorrow."))
    assert result["meetings_mentioned"][0]["date_phrase"] == "tomorrow"


def test_mock_llm_detects_meeting_noun_form_with_digit_duration():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("The meeting is in 10 days."))
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 10 days"


def test_mock_llm_detects_catch_up_phrase_as_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("Let's catch up in 10 days."))
    assert len(result["meetings_mentioned"]) == 1


def test_mock_llm_detects_both_a_commitment_and_a_relative_date_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(
        _email("I will send the proposal. We can meet in 2 weeks to go over it.")
    )
    assert len(result["commitments_mentioned"]) == 1
    assert result["commitments_mentioned"][0]["class"] == "mine"
    assert len(result["meetings_mentioned"]) == 1
    assert result["meetings_mentioned"][0]["date_phrase"] == "in 2 weeks"


def test_mock_llm_does_not_detect_historical_meeting_mention_as_a_meeting():
    provider = MockLLMProvider()
    result = provider.analyze_email(_email("We met last week and it went well."))
    # "met" (past tense) is a different word from the "meet" trigger -- this is
    # intentionally never recognized as a meeting mention at all by the keyword-based mock.
    assert result["meetings_mentioned"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_schemas.py tests/test_mock_llm_provider.py -v`
Expected: FAIL — `EmailAnalysis` has no field `people_mentioned` / `KeyError: 'people_mentioned'`

- [ ] **Step 3: Extend `app/analysis/schemas.py`**

Add these new classes above `EmailAnalysis`, and the new fields inside it:

```python
# app/analysis/schemas.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class MentionedPerson(BaseModel):
    name: str
    email: str | None = None
    org: str | None = None
    role_hint: str | None = None


class MentionedProject(BaseModel):
    name: str
    org: str | None = None
    objective_hint: str | None = None


class RawCommitment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    what: str
    commitment_class: Literal["mine", "owed_to_me", "theirs", "recap"] = Field(alias="class")
    owed_by: str | None = None
    owed_to: str | None = None
    date_phrase: str | None = None
    importance_hint: str | None = None


class RawMeeting(BaseModel):
    date_phrase: str | None = None
    attendees: list[str] = Field(default_factory=list)
    is_past: bool = False
    actions_raised: list[str] = Field(default_factory=list)


class RawPersonalItem(BaseModel):
    item_type: str
    description: str
    date_phrase: str | None = None


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
    people_mentioned: list[MentionedPerson] = Field(default_factory=list)
    projects_mentioned: list[MentionedProject] = Field(default_factory=list)
    commitments_mentioned: list[RawCommitment] = Field(default_factory=list)
    meetings_mentioned: list[RawMeeting] = Field(default_factory=list)
    personal_items_mentioned: list[RawPersonalItem] = Field(default_factory=list)
    goal_pillar: str = ""
    label_applied: Literal[
        "Needs reply: ASAP", "Needs reply: Soon", "Read only", "Delete", "Undecided"
    ] = "Undecided"
    confidence: float = 0.0
```

(This replaces the whole file's `Fact`/`EmailAnalysis` section — the existing `email_id`
through `products` fields are unchanged, only reordered above the new additions for
readability; do not remove or rename any existing field.)

- [ ] **Step 4: Extend `app/providers/llm/mock.py`**

Add near the top of the file, alongside the existing pattern constants:

```python
from app.entities.dates import find_date_phrase

# Negative lookahead excludes "...will meet" -- that phrasing is a meeting signal, not a
# commitment (spec S5.1.1's explicit "We will meet in 2 weeks" example: meeting detected,
# no commitment). "I will send"/"I'll follow up"/"we will confirm" etc. still match.
_MINE_COMMITMENT_PATTERN = re.compile(r"\b(?:i will|i'll|we will)\b(?!\s+meet\b)", re.IGNORECASE)
_OWED_TO_ME_COMMITMENT_PATTERN = re.compile(r"\bcould you\b|\bcan you\b", re.IGNORECASE)
# Broadened per spec S5.1.1: a meeting doesn't require an explicit invitation -- the noun
# forms "meeting"/"meetings" and the phrase "catch up" must also trigger detection. Note
# "met" (past tense) intentionally does NOT match "meet" -- see
# test_mock_llm_does_not_detect_historical_meeting_mention_as_a_meeting.
_MEETING_LANGUAGE = re.compile(r"\b(meet|meeting|meetings|call|sync|catch up)\b", re.IGNORECASE)
```

Inside `MockLLMProvider.analyze_email`, before the final `return` statement, add:

```python
        date_phrase = find_date_phrase(body)

        people_mentioned = [
            {
                "name": email.from_.name or email.from_.email,
                "email": email.from_.email,
                "org": None,
                "role_hint": None,
            }
        ]

        commitments_mentioned = []
        if _MINE_COMMITMENT_PATTERN.search(body):
            commitments_mentioned.append(
                {
                    "what": "follow up",
                    "class": "mine",
                    "owed_by": None,
                    "owed_to": None,
                    "date_phrase": date_phrase,
                    "importance_hint": None,
                }
            )
        if _OWED_TO_ME_COMMITMENT_PATTERN.search(body):
            commitments_mentioned.append(
                {
                    "what": "requested action",
                    "class": "owed_to_me",
                    "owed_by": None,
                    "owed_to": None,
                    "date_phrase": date_phrase,
                    "importance_hint": None,
                }
            )

        meetings_mentioned = []
        if _MEETING_LANGUAGE.search(body):
            meetings_mentioned.append(
                {
                    "date_phrase": date_phrase,
                    "attendees": [],
                    "is_past": False,
                    "actions_raised": [],
                }
            )

        label_applied = "Needs reply: ASAP" if buying_signals else "Read only"
```

Then extend the `return` dict (which already exists) with:

```python
            "people_mentioned": people_mentioned,
            "projects_mentioned": [],
            "commitments_mentioned": commitments_mentioned,
            "meetings_mentioned": meetings_mentioned,
            "personal_items_mentioned": [],
            "goal_pillar": "Sales",
            "label_applied": label_applied,
            "confidence": 0.8,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_analysis_schemas.py tests/test_mock_llm_provider.py -v`
Expected: PASS (21 tests: 4 in test_analysis_schemas.py, 17 in test_mock_llm_provider.py)

- [ ] **Step 6: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/analysis/schemas.py app/providers/llm/mock.py tests/test_analysis_schemas.py tests/test_mock_llm_provider.py
git commit -m "feat: extend EmailAnalysis with entity-signal fields and update MockLLMProvider"
```

---

## Task 6: Update Real LLM Provider Prompts

**Files:**
- Modify: `app/providers/llm/claude.py`
- Test: `tests/test_llm_provider_prompts.py`

**Interfaces:**
- Consumes: nothing new
- Produces: an updated `_ANALYSIS_INSTRUCTIONS` string in `app.providers.llm.claude` (also used, unmodified, by `app.providers.llm.openai` via its existing import). No new interface consumed elsewhere.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_provider_prompts.py
from app.providers.llm.claude import _ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_mention_entity_signal_fields():
    for expected in [
        "people_mentioned",
        "projects_mentioned",
        "commitments_mentioned",
        "meetings_mentioned",
        "personal_items_mentioned",
        "goal_pillar",
        "label_applied",
        "confidence",
    ]:
        assert expected in _ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_do_not_ask_the_llm_for_canonical_ids():
    lowered = _ANALYSIS_INSTRUCTIONS.lower()
    assert "per-" not in lowered
    assert "prj-" not in lowered
    assert "canonical id" not in lowered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_provider_prompts.py -v`
Expected: FAIL — `people_mentioned` not present in the current `_ANALYSIS_INSTRUCTIONS` string

- [ ] **Step 3: Update `_ANALYSIS_INSTRUCTIONS` in `app/providers/llm/claude.py`**

Replace the existing `_ANALYSIS_INSTRUCTIONS` constant with:

```python
_ANALYSIS_INSTRUCTIONS = (
    "You are a sales email analyst. Given the email below, return ONLY a JSON object with keys: "
    "summary, intent, entities, facts (list of {subject,predicate,object}), requirements, pain_points, "
    "buying_signals, objections, competitors, pricing_mentions, commitments, action_items, meetings, "
    "people, companies, products, "
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
    "Do not invent or assign any canonical entity ID (e.g. never output anything shaped like 'PER-042' "
    "or 'PRJ-011') -- only describe what you observe; ID assignment is handled separately. "
    "Use empty lists/strings for anything not present. No prose, JSON only."
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_provider_prompts.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/providers/llm/claude.py tests/test_llm_provider_prompts.py
git commit -m "feat: extend Claude/OpenAI analysis prompt to request entity signals, never canonical IDs"
```

---

## Task 7: Canonical Resolution Logic

**Files:**
- Create: `app/entities/resolution.py`
- Test: `tests/test_entities_resolution.py`

**Interfaces:**
- Consumes: `Person`/`Project`/`Commitment`/`FollowUp`/`Meeting`/`PersonalItem` (Task 2), the 6 repositories (Task 3), `next_id` (Task 1), `resolve_date_phrase` (Task 4), `normalize_text` (existing, `app.knowledge.normalize`)
- Produces: `resolve_person`, `resolve_project`, `resolve_commitment`, `resolve_meeting`, `resolve_personal_item`, `derive_follow_up` in `app.entities.resolution`. Task 8's pipeline stage calls these directly.

**Design notes carried from the spec (§6):** Person never merges on name alone (only exact
email). Project merges only on exact normalized name + same `entity` + same `goal_pillar`
(no fuzzy tier, no `review_flag` on Project). Commitment/Meeting/PersonalItem merge only on
exact natural-key match within the same thread (or sender, for PersonalItem). `resolve_person`
takes an explicit `is_sender: bool | None` so the caller (Task 8) states whether this mention
came from the email's `from_` (`True`), an envelope `to`/`cc` recipient (`False`), or an
LLM-only mention with no envelope match (`None`, in which case no contact timestamp is
touched) — this keeps the timestamp-touching behavior simple and explicit rather than
guessed. `derive_follow_up` is idempotent per `commitment_id` (or per `thread_id` when there
is no commitment) so re-resolving the same commitment never creates a duplicate `FollowUp`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entities_resolution.py
from datetime import datetime, timezone

import mongomock
import pytest

from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)
from app.entities.resolution import (
    derive_follow_up,
    resolve_commitment,
    resolve_meeting,
    resolve_person,
    resolve_personal_item,
    resolve_project,
)

_NOW = datetime(2026, 9, 13, 10, 30, tzinfo=timezone.utc)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


def test_resolve_person_merges_on_exact_email(db):
    first = resolve_person(db, {"name": "Jane", "email": "jane@example.com"}, is_sender=True, now=_NOW)
    second = resolve_person(db, {"name": "Jane Doe", "email": "Jane@Example.com"}, is_sender=True, now=_NOW)

    assert first == second
    assert PersonRepository(db).find_many({}).__len__() == 1


def test_resolve_person_never_merges_on_name_alone_and_flags_for_review(db):
    first = resolve_person(db, {"name": "Sam Lee", "email": None}, is_sender=None, now=_NOW)
    second = resolve_person(db, {"name": "Sam Lee", "email": None}, is_sender=None, now=_NOW)

    assert first != second
    people = PersonRepository(db).find_many({})
    assert len(people) == 2
    assert all(p["review_flag"] is True for p in people)
    # The "email" key must be OMITTED (not stored as null) for a no-email Person -- a
    # sparse unique index on real MongoDB only excludes a document where the field is
    # entirely missing, not one where it is present with value null. Storing "email": null
    # for two such People would collide on people.email's sparse-unique index (Task 3) on
    # real MongoDB, even though mongomock's more lenient interpretation would not catch it.
    assert all("email" not in p for p in people)


def test_resolve_person_touches_last_inbound_when_sender(db):
    person_id = resolve_person(db, {"name": "Jane", "email": "jane@example.com"}, is_sender=True, now=_NOW)
    stored = PersonRepository(db).find_one({"id": person_id})
    assert stored["last_inbound"] is not None
    assert stored["last_outbound"] is None


def test_resolve_project_merges_on_exact_name_entity_and_goal_pillar(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "renewal", "org": "Acme"}, goal_pillar="Sales")

    assert first == second
    assert len(ProjectRepository(db).find_many({})) == 1


def test_resolve_project_does_not_merge_across_different_entities(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "Renewal", "org": "OtherCo"}, goal_pillar="Sales")

    assert first != second


def test_resolve_project_does_not_merge_without_goal_pillar_corroboration(db):
    first = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Sales")
    second = resolve_project(db, {"name": "Renewal", "org": "Acme"}, goal_pillar="Support")

    assert first != second


def test_resolve_commitment_deduplicates_within_same_thread(db):
    raw = {"what": "Send updated case study", "class": "mine", "date_phrase": None}
    first = resolve_commitment(
        db, thread_id="thread_1", raw=raw, message_id="msg_001", made_on=_NOW,
        resolved_date=None, date_type=None, goal_pillar="Sales", project_id=None,
    )
    second = resolve_commitment(
        db, thread_id="thread_1", raw={"what": "send updated case study", "class": "mine", "date_phrase": None},
        message_id="msg_002", made_on=_NOW, resolved_date=None, date_type=None,
        goal_pillar="Sales", project_id=None,
    )

    assert first == second
    assert len(CommitmentRepository(db).all_for_thread("thread_1")) == 1


def test_resolve_commitment_creates_new_for_different_date(db):
    raw_a = {"what": "Send case study", "class": "mine", "date_phrase": None}
    first = resolve_commitment(
        db, thread_id="thread_1", raw=raw_a, message_id="msg_001", made_on=_NOW,
        resolved_date=datetime(2026, 9, 20, tzinfo=timezone.utc), date_type="inferred",
        goal_pillar="Sales", project_id=None,
    )
    second = resolve_commitment(
        db, thread_id="thread_1", raw=raw_a, message_id="msg_002", made_on=_NOW,
        resolved_date=datetime(2026, 9, 27, tzinfo=timezone.utc), date_type="inferred",
        goal_pillar="Sales", project_id=None,
    )

    assert first != second


def test_resolve_meeting_deduplicates_on_thread_and_date(db):
    date = datetime(2026, 9, 20, tzinfo=timezone.utc)
    first = resolve_meeting(
        db, thread_id="thread_1", date=date, raw={"attendees": [], "actions_raised": []}, actionable=True
    )
    second = resolve_meeting(
        db, thread_id="thread_1", date=date, raw={"attendees": [], "actions_raised": []}, actionable=True
    )

    assert first == second
    assert len(MeetingRepository(db).all_for_thread("thread_1")) == 1


def test_resolve_meeting_stores_actionable_flag(db):
    meeting_id = resolve_meeting(
        db, thread_id="thread_2", date=None, raw={"attendees": [], "actions_raised": []}, actionable=False
    )
    stored = MeetingRepository(db).find_one({"id": meeting_id})
    assert stored["actionable"] is False


def test_resolve_personal_item_deduplicates_on_sender_and_description(db):
    raw = {"item_type": "reminder", "description": "Renew passport"}
    first = resolve_personal_item(db, sender_email="jane@example.com", raw=raw, resolved_date=None)
    second = resolve_personal_item(db, sender_email="Jane@Example.com", raw={"item_type": "reminder", "description": "renew passport"}, resolved_date=None)

    assert first == second
    assert len(PersonalItemRepository(db).find_many({})) == 1


def test_derive_follow_up_from_commitment_is_idempotent(db):
    first = derive_follow_up(db, commitment_id="COM-001", thread_id=None)
    second = derive_follow_up(db, commitment_id="COM-001", thread_id=None)

    assert first == second
    stored = FollowUpRepository(db).find_one({"id": first})
    assert stored["commitment_id"] == "COM-001"
    assert stored["thread_id"] is None


def test_derive_follow_up_from_thread_when_no_commitment(db):
    follow_up_id = derive_follow_up(db, commitment_id=None, thread_id="thread_1")
    stored = FollowUpRepository(db).find_one({"id": follow_up_id})
    assert stored["thread_id"] == "thread_1"
    assert stored["commitment_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entities_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.entities.resolution'`

- [ ] **Step 3: Implement `app/entities/resolution.py`**

```python
# app/entities/resolution.py
from datetime import datetime
from typing import Any

from pymongo.database import Database

from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    MeetingRepository,
    PersonalItemRepository,
    PersonRepository,
    ProjectRepository,
)
from app.entities.ids import next_id
from app.entities.models import Commitment, FollowUp, Meeting, Person, PersonalItem, Project
from app.knowledge.normalize import normalize_text


def resolve_person(
    db: Database, mention: dict[str, Any], is_sender: bool | None, now: datetime
) -> str:
    repo = PersonRepository(db)
    email = (mention.get("email") or "").strip().lower() or None

    if email:
        existing = repo.find_one({"email": email})
        if existing:
            update: dict[str, Any] = {}
            if is_sender is True:
                update["last_inbound"] = now.isoformat()
            elif is_sender is False:
                update["last_outbound"] = now.isoformat()
            if update:
                repo.upsert_by_key({"id": existing["id"]}, {**existing, **update})
            return existing["id"]

        person_id = next_id(db, "PER-")
        person = Person(
            id=person_id,
            name=mention.get("name") or email,
            email=email,
            org=mention.get("org"),
            review_flag=False,
            last_inbound=now if is_sender is True else None,
            last_outbound=now if is_sender is False else None,
        )
        repo.upsert_by_key({"id": person_id}, person.model_dump(mode="json"))
        return person_id

    # No email present: never merge on name alone -- always create new, flagged for review.
    person_id = next_id(db, "PER-")
    person = Person(
        id=person_id,
        name=mention.get("name") or "Unknown",
        email=None,
        org=mention.get("org"),
        review_flag=True,
    )
    # exclude={"email"}: MongoDB's sparse unique index on people.email (Task 3) only
    # excludes a document where the field is entirely MISSING -- a document with
    # email explicitly set to null still gets indexed with key null, and a second such
    # document would collide on the unique constraint. Omitting the key entirely (rather
    # than storing "email": null) is what actually makes two no-email People coexist on
    # real MongoDB, not just under mongomock's more lenient interpretation of sparse+null.
    repo.upsert_by_key({"id": person_id}, person.model_dump(mode="json", exclude={"email"}))
    return person_id


def resolve_project(db: Database, mention: dict[str, Any], goal_pillar: str) -> str:
    repo = ProjectRepository(db)
    name_normalized = normalize_text(mention["name"])
    entity = mention.get("org")

    candidates = repo.find_many({"entity": entity}) if entity else []
    for candidate in candidates:
        if (
            normalize_text(candidate["project"]) == name_normalized
            and candidate.get("goal_pillar") == goal_pillar
        ):
            return candidate["id"]

    project_id = next_id(db, "PRJ-")
    project = Project(id=project_id, project=mention["name"], entity=entity, goal_pillar=goal_pillar)
    repo.upsert_by_key({"id": project_id}, project.model_dump(mode="json"))
    return project_id


def resolve_commitment(
    db: Database,
    thread_id: str,
    raw: dict[str, Any],
    message_id: str,
    made_on: datetime,
    resolved_date: datetime | None,
    date_type: str | None,
    goal_pillar: str,
    project_id: str | None,
) -> str:
    repo = CommitmentRepository(db)
    what_normalized = normalize_text(raw["what"])
    resolved_date_iso = resolved_date.isoformat() if resolved_date else None

    for candidate in repo.all_for_thread(thread_id):
        if (
            normalize_text(candidate["what"]) == what_normalized
            and candidate["class"] == raw["class"]
            and candidate.get("committed_date") == resolved_date_iso
        ):
            return candidate["id"]

    commitment_id = next_id(db, "COM-")
    commitment = Commitment(
        id=commitment_id,
        what=raw["what"],
        commitment_class=raw["class"],
        importance=raw.get("importance_hint"),
        owed_by=raw.get("owed_by"),
        owed_to=raw.get("owed_to"),
        source_record=message_id,
        made_on=made_on,
        committed_date=resolved_date,
        date_type=date_type,
        goal_pillar=goal_pillar,
        project_id=project_id,
    )
    doc = commitment.model_dump(mode="json", by_alias=True)
    doc["thread_id"] = thread_id
    repo.upsert_by_key({"id": commitment_id}, doc)
    return commitment_id


def resolve_meeting(
    db: Database, thread_id: str, date: datetime | None, raw: dict[str, Any], actionable: bool
) -> str:
    repo = MeetingRepository(db)
    date_iso = date.isoformat() if date else None

    for candidate in repo.all_for_thread(thread_id):
        if candidate.get("date") == date_iso:
            return candidate["id"]

    meeting_id = next_id(db, "MTG-")
    meeting = Meeting(
        id=meeting_id,
        date=date,
        attendees=raw.get("attendees", []),
        actions_raised=raw.get("actions_raised", []),
        actionable=actionable,
    )
    doc = meeting.model_dump(mode="json")
    doc["thread_id"] = thread_id
    repo.upsert_by_key({"id": meeting_id}, doc)
    return meeting_id


def resolve_personal_item(
    db: Database, sender_email: str, raw: dict[str, Any], resolved_date: datetime | None
) -> str:
    repo = PersonalItemRepository(db)
    sender_normalized = sender_email.strip().lower()
    description_normalized = normalize_text(raw["description"])

    for candidate in repo.find_many({"sender_email": sender_normalized}):
        if normalize_text(candidate["description"]) == description_normalized:
            return candidate["id"]

    item_id = next_id(db, "PSN-")
    item = PersonalItem(
        id=item_id,
        type=raw["item_type"],
        description=raw["description"],
        date_or_deadline=resolved_date,
    )
    doc = item.model_dump(mode="json")
    doc["sender_email"] = sender_normalized
    repo.upsert_by_key({"id": item_id}, doc)
    return item_id


def derive_follow_up(db: Database, commitment_id: str | None, thread_id: str | None) -> str:
    repo = FollowUpRepository(db)

    if commitment_id is not None:
        existing = repo.find_one({"commitment_id": commitment_id})
        if existing:
            return existing["id"]
        follow_up_id = next_id(db, "FU-")
        follow_up = FollowUp(id=follow_up_id, commitment_id=commitment_id)
        repo.upsert_by_key({"id": follow_up_id}, follow_up.model_dump(mode="json"))
        return follow_up_id

    existing = repo.find_one({"thread_id": thread_id})
    if existing:
        return existing["id"]
    follow_up_id = next_id(db, "FU-")
    follow_up = FollowUp(id=follow_up_id, thread_id=thread_id)
    repo.upsert_by_key({"id": follow_up_id}, follow_up.model_dump(mode="json"))
    return follow_up_id
```

Note: `resolve_commitment`/`resolve_meeting` store an extra `thread_id` field on the
document (not part of the `Commitment`/`Meeting` Pydantic model itself, which per the spec
has no `thread_id` field) purely so `CommitmentRepository.all_for_thread`/
`MeetingRepository.all_for_thread` (Task 3) can query by it — this is a storage-only
convenience field, never returned by the public resolution function's return value (just
the id), and never exposed through `entities_referenced` (which only ever holds IDs).
Similarly `resolve_personal_item` stores `sender_email` for its own dedup lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entities_resolution.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/entities/resolution.py tests/test_entities_resolution.py
git commit -m "feat: add deterministic canonical entity resolution (Person/Project/Commitment/Meeting/PersonalItem/FollowUp)"
```

---

## Task 8: Pipeline Integration

**Files:**
- Modify: `app/processing/models.py` (add `ENTITIES_PROCESSED` stage)
- Modify: `app/database/repositories.py` (add `EmailRepository.set_entity_metadata`)
- Modify: `app/pipeline.py` (wire the new stage in)
- Test: `tests/test_pipeline_entities.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7
- Produces: `run_pipeline` now also populates `record_id`/`source_type`/`source_link`/`date`/`entities_referenced`/`goal_pillar`/`label_applied`/`confidence` on every completed email's document.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_entities.py
import mongomock
import pytest

from app.config.settings import Settings
from app.database.indexes import initialize_indexes
from app.database.repositories import (
    CommitmentRepository,
    FollowUpRepository,
    PersonRepository,
)
from app.pipeline import run_pipeline
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.email.mock import MockEmailProvider
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


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["cos_sales_test"]
    initialize_indexes(database)
    return database


@pytest.fixture
def settings():
    return Settings(email_provider="mock", calendar_provider="mock", llm_provider="mock")


def test_pipeline_populates_entity_metadata_on_the_email(db, settings):
    payloads = [_raw_email("1a08090646ebaa45", "I will send the proposal on Friday.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    assert stored["record_id"] == "1a08090646ebaa45"
    assert stored["source_type"] == "gmail"
    assert stored["source_link"] == "https://mail.google.com/mail/u/0/#all/1a08090646ebaa45"
    assert stored["date"] == "2026-09-13"
    assert stored["goal_pillar"] == "Sales"
    assert stored["label_applied"] in {"Needs reply: ASAP", "Read only"}
    assert isinstance(stored["confidence"], float)

    entities_referenced = stored["entities_referenced"]
    assert len(entities_referenced["people"]) == 1
    assert len(entities_referenced["commitments"]) == 1
    assert len(entities_referenced["follow_ups"]) == 1
    assert entities_referenced["projects"] == []
    assert entities_referenced["meetings"] == []
    assert entities_referenced["personal"] == []

    person = PersonRepository(db).find_one({"id": entities_referenced["people"][0]})
    assert person["email"] == "john@example.com"

    commitment = CommitmentRepository(db).find_one({"id": entities_referenced["commitments"][0]})
    assert commitment["class"] == "mine"

    follow_up = FollowUpRepository(db).find_one({"id": entities_referenced["follow_ups"][0]})
    assert follow_up["commitment_id"] == entities_referenced["commitments"][0]


def test_pipeline_sets_source_link_to_none_for_non_gmail_shaped_message_id(db, settings):
    payloads = [_raw_email("not-a-gmail-hex-id", "Just checking in.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "not-a-gmail-hex-id"}, {"_id": 0})
    assert stored["source_link"] is None


def test_pipeline_reuses_same_person_across_two_emails_in_same_thread(db, settings):
    payloads = [
        _raw_email("1111111111111111", "I will send the proposal on Friday."),
        _raw_email(
            "2222222222222222",
            "Following up on my earlier note.",
            in_reply_to="1111111111111111",
            references=["1111111111111111"],
        ),
    ]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    assert PersonRepository(db).find_many({}).__len__() == 1


def test_pipeline_detects_relative_date_meeting_with_no_commitment_and_no_follow_up(db, settings):
    from app.database.repositories import FollowUpRepository, MeetingRepository

    payloads = [_raw_email("1a08090646ebaa45", "Sounds good. We will meet in 2 weeks.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    entities_referenced = stored["entities_referenced"]
    assert entities_referenced["commitments"] == []
    assert len(entities_referenced["meetings"]) == 1

    meeting = MeetingRepository(db).find_one({"id": entities_referenced["meetings"][0]})
    assert meeting["actionable"] is True
    # 2026-09-13 (this email's timestamp) + 14 days = 2026-09-27
    assert meeting["date"].startswith("2026-09-27")

    # The core corrected rule: a Meeting must never trigger a FollowUp by itself.
    assert entities_referenced["follow_ups"] == []
    assert FollowUpRepository(db).find_many({}) == []


def test_pipeline_does_not_mark_historical_meeting_mention_as_actionable(db, settings):
    payloads = [_raw_email("1a08090646ebaa45", "We met last week and it went well.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    # MockLLMProvider never recognizes "met" (past tense) as a meeting mention at all --
    # see test_mock_llm_does_not_detect_historical_meeting_mention_as_a_meeting (Task 5).
    assert stored["entities_referenced"]["meetings"] == []


def test_pipeline_marks_failed_at_entities_processed_without_losing_prior_stage_data(
    db, settings, monkeypatch
):
    # A shape-invalid EmailAnalysis field would fail pydantic validation during the
    # existing ANALYZED stage (inside analyze_email_with_validation), not the new
    # ENTITIES_PROCESSED stage -- that would test the wrong stage entirely. To reach a
    # failure specifically inside the new stage, the EmailAnalysis must validate
    # successfully; the failure must come from entity resolution itself. Monkeypatching
    # the resolver app/pipeline.py actually calls is the precise way to do that.
    import app.pipeline as pipeline_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated entity resolution failure")

    monkeypatch.setattr(pipeline_module, "resolve_person", _boom)

    payloads = [_raw_email("1a08090646ebaa45", "I will send the proposal on Friday.")]
    run_pipeline(db, MockEmailProvider(payloads=payloads), MockLLMProvider(), MockCalendarProvider(), settings)

    stored = db.emails.find_one({"message_id": "1a08090646ebaa45"}, {"_id": 0})
    assert stored["processing_status"]["stage"] == "FAILED"
    assert stored["processing_status"]["failed_stage"] == "ENTITIES_PROCESSED"
    assert "simulated entity resolution failure" in stored["processing_status"]["error"]
    # Knowledge/context from earlier stages must still be persisted, not rolled back.
    assert db.context_snapshots.count_documents({}) == 1
    assert db.knowledge_items.count_documents({}) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_entities.py -v`
Expected: FAIL — `KeyError: 'record_id'` (the email document has no entity metadata yet)

- [ ] **Step 3: Add `ENTITIES_PROCESSED` to `app/processing/models.py`**

```python
class ProcessingStage(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    THREADED = "THREADED"
    ANALYZED = "ANALYZED"
    CONTEXT_BUILT = "CONTEXT_BUILT"
    KNOWLEDGE_PROCESSED = "KNOWLEDGE_PROCESSED"
    ENTITIES_PROCESSED = "ENTITIES_PROCESSED"
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
    ProcessingStage.ENTITIES_PROCESSED,
    ProcessingStage.REPLY_PROCESSED,
    ProcessingStage.MEETING_PROCESSED,
    ProcessingStage.COMPLETED,
]
```

- [ ] **Step 4: Add `EmailRepository.set_entity_metadata` in `app/database/repositories.py`**

Add this method inside the existing `EmailRepository` class, after `set_stage`:

```python
    def set_entity_metadata(
        self,
        message_id: str,
        record_id: str,
        source_type: str,
        source_link: str | None,
        date: str,
        entities_referenced: dict[str, list[str]],
        goal_pillar: str,
        label_applied: str,
        confidence: float,
    ) -> None:
        self._collection.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "record_id": record_id,
                    "source_type": source_type,
                    "source_link": source_link,
                    "date": date,
                    "entities_referenced": entities_referenced,
                    "goal_pillar": goal_pillar,
                    "label_applied": label_applied,
                    "confidence": confidence,
                }
            },
        )
```

- [ ] **Step 5: Wire the new stage into `app/pipeline.py`**

Add these imports at the top of `app/pipeline.py`, alongside the existing ones:

```python
import re

from app.entities.dates import resolve_date_phrase
from app.entities.extraction import envelope_people
from app.entities.resolution import (
    derive_follow_up,
    resolve_commitment,
    resolve_meeting,
    resolve_person,
    resolve_personal_item,
    resolve_project,
)

_GMAIL_INTERNAL_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
```

Add a new helper function, alongside the existing `_process_knowledge` function:

```python
def _process_entities(
    db,
    thread_id: str,
    email: Email,
    analysis: EmailAnalysis,
    reference_now: datetime,
) -> dict[str, list[str]]:
    # reference_now is the email's OWN timestamp, not wall-clock "now" -- this matches the
    # existing detect_meeting's established pattern (app/calendar/detector.py, called with
    # email.timestamp) so a re-run days later resolves the same relative phrase the same way.
    entities_referenced: dict[str, list[str]] = {
        "people": [], "projects": [], "commitments": [],
        "follow_ups": [], "meetings": [], "personal": [],
    }

    envelope = {addr.email.lower(): addr for addr in envelope_people(email)}
    sender_email = email.from_.email.lower()

    for mention in analysis.people_mentioned:
        mention_email = (mention.email or "").lower() or None
        is_sender = None
        if mention_email and mention_email == sender_email:
            is_sender = True
        elif mention_email and mention_email in envelope:
            is_sender = False
        person_id = resolve_person(
            db,
            {"name": mention.name, "email": mention.email, "org": mention.org},
            is_sender=is_sender,
            now=reference_now,
        )
        entities_referenced["people"].append(person_id)

    project_id_by_name: dict[str, str] = {}
    for mention in analysis.projects_mentioned:
        project_id = resolve_project(
            db, {"name": mention.name, "org": mention.org}, goal_pillar=analysis.goal_pillar
        )
        entities_referenced["projects"].append(project_id)
        project_id_by_name[mention.name] = project_id

    # FollowUps are derived ONLY from a resolved Commitment (spec S5.1.1 correction) --
    # a Meeting or PersonalItem NEVER triggers a FollowUp by itself, no matter how
    # "actionable" the meeting is. Do not add a fallback branch here.
    for raw_commitment in analysis.commitments_mentioned:
        resolved_date, date_type = resolve_date_phrase(raw_commitment.date_phrase, reference_now)
        commitment_id = resolve_commitment(
            db,
            thread_id=thread_id,
            raw=raw_commitment.model_dump(mode="json", by_alias=True),
            message_id=email.message_id,
            made_on=reference_now,
            resolved_date=resolved_date,
            date_type=date_type,
            goal_pillar=analysis.goal_pillar,
            project_id=None,
        )
        entities_referenced["commitments"].append(commitment_id)
        follow_up_id = derive_follow_up(db, commitment_id=commitment_id, thread_id=None)
        entities_referenced["follow_ups"].append(follow_up_id)

    for raw_meeting in analysis.meetings_mentioned:
        resolved_date, _ = resolve_date_phrase(raw_meeting.date_phrase, reference_now)
        # The actionable signal (spec S4.6): true for any future-oriented meeting mention,
        # even a vague one with no precise resolved_date -- false only when the LLM (or,
        # for MockLLMProvider, the simple absence of a "meet" match on past-tense "met")
        # flagged it as historical.
        actionable = not raw_meeting.is_past
        meeting_id = resolve_meeting(
            db,
            thread_id=thread_id,
            date=resolved_date,
            raw=raw_meeting.model_dump(mode="json"),
            actionable=actionable,
        )
        entities_referenced["meetings"].append(meeting_id)

    for raw_item in analysis.personal_items_mentioned:
        resolved_date, _ = resolve_date_phrase(raw_item.date_phrase, reference_now)
        item_id = resolve_personal_item(
            db, sender_email=sender_email, raw=raw_item.model_dump(mode="json"), resolved_date=resolved_date
        )
        entities_referenced["personal"].append(item_id)

    return entities_referenced
```

In `run_pipeline`, immediately after the existing `KNOWLEDGE_PROCESSED` block (right after
the line `email_repo.set_stage(email.message_id, ProcessingStage.KNOWLEDGE_PROCESSED.value)`
and before the existing `current_stage = ProcessingStage.REPLY_PROCESSED` line), insert:

```python
            current_stage = ProcessingStage.ENTITIES_PROCESSED
            # email.timestamp, not datetime.now() -- matches detect_meeting's existing
            # reference-date pattern, so relative phrases resolve consistently regardless
            # of when the pipeline actually runs.
            entities_referenced = _process_entities(db, thread_id, email, analysis, email.timestamp)
            source_link = (
                f"https://mail.google.com/mail/u/0/#all/{email.message_id}"
                if _GMAIL_INTERNAL_ID_PATTERN.match(email.message_id)
                else None
            )
            email_repo.set_entity_metadata(
                message_id=email.message_id,
                record_id=email.message_id,
                source_type="gmail",
                source_link=source_link,
                date=email.timestamp.date().isoformat(),
                entities_referenced=entities_referenced,
                goal_pillar=analysis.goal_pillar,
                label_applied=analysis.label_applied,
                confidence=analysis.confidence,
            )
            email_repo.set_stage(email.message_id, ProcessingStage.ENTITIES_PROCESSED.value)
```

(The existing broad `except Exception` block already wrapping this whole per-email
section catches any failure here exactly like every other stage — no new exception
handling is required.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_entities.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS (every existing test, including `tests/test_pipeline.py`, unchanged)

- [ ] **Step 8: Commit**

```bash
git add app/processing/models.py app/database/repositories.py app/pipeline.py tests/test_pipeline_entities.py
git commit -m "feat: wire canonical entity extraction/resolution into the pipeline as a new stage"
```

---

## Task 9: Expose Entity Data Through the MCP Tools

**Files:**
- Modify: `app/mcp/tools.py`
- Test: `tests/test_mcp_tools.py` (extend)

**Interfaces:**
- Consumes: the `entities_referenced`/`goal_pillar`/`label_applied`/`confidence`/`record_id`/`source_type`/`source_link`/`date` fields Task 8 now writes onto every `emails` document
- Produces: `list_processed_emails`'s returned dicts gain these fields; no new tool, no new interface for other tasks to consume.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_tools.py`:

```python
def test_list_processed_emails_includes_entity_metadata(db, settings):
    process_email(
        db,
        parse_email(_raw_email("1a08090646ebaa45", "I will send the proposal on Friday.")),
        MockLLMProvider(),
        MockCalendarProvider(),
        settings,
    )

    results = list_processed_emails(db, limit=50)

    entry = results[0]
    assert entry["record_id"] == "1a08090646ebaa45"
    assert entry["source_type"] == "gmail"
    assert entry["source_link"] == "https://mail.google.com/mail/u/0/#all/1a08090646ebaa45"
    assert entry["date"] == "2026-09-13"
    assert entry["goal_pillar"] == "Sales"
    assert entry["label_applied"] in {"Needs reply: ASAP", "Read only"}
    assert isinstance(entry["confidence"], float)
    assert len(entry["entities_referenced"]["people"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_tools.py -v -k entity_metadata`
Expected: FAIL with `KeyError: 'record_id'`

- [ ] **Step 3: Extend `list_processed_emails` in `app/mcp/tools.py`**

In the `results.append({...})` block inside `list_processed_emails`, add these keys
alongside the existing ones:

```python
                "record_id": email["record_id"],
                "source_type": email["source_type"],
                "source_link": email["source_link"],
                "date": email["date"],
                "entities_referenced": email["entities_referenced"],
                "goal_pillar": email["goal_pillar"],
                "label_applied": email["label_applied"],
                "confidence": email["confidence"],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: PASS (every test in the file, including the new one)

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat: surface canonical entity references and classification via list_processed_emails"
```
