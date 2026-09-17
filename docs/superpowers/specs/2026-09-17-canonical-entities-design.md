# CoS Sales Agent — Canonical Entity Extraction & Resolution (Phase 4)

Status: approved design, pending implementation plan.

## 1. Purpose

Extend the pipeline so that, in addition to the existing thread-scoped `knowledge_items`,
ingesting an email also extracts and resolves references to persistent, cross-thread
**canonical entities** — People, Projects, Commitments, FollowUps, Meetings, and
PersonalItems — and cross-references them back onto the email as `entities_referenced`.
Also adds lightweight classification metadata (`goal_pillar`, `label_applied`,
`confidence`) to every processed email.

This is additive: it introduces one new pipeline stage and a new package of canonical
entity models/repositories/resolution logic. It does not change `run_pipeline`'s existing
stages, `knowledge_items`, `context_snapshots`, `reply_drafts`, or `calendar_actions`
behavior.

## 1.1 End-to-End Flow

```text
Gmail (Claude's connector — unchanged, no code here)
  |
  v
process_email(email)
  |
  v
Deterministic Extraction (no LLM, no DB)
  - names/emails/domains from headers + a body regex scan
  - thread_id via the existing resolve_thread_id (unchanged)
  - date-phrase -> actual date, once a raw phrase exists (see below)
  |
  v
LLM Semantic Extraction (the existing single analyze_email call, extended)
  - people / projects / commitments / meetings / personal items mentioned
  - raw date phrases, goal_pillar, label_applied, confidence
  - never emits a canonical ID
  |
  v
Canonical Entity Resolution (deterministic, app/entities/resolution.py)
  - matches to an existing canonical entity, or creates a new one via next_id()
  |
  v
Persist / Update Canonical Entities
  (people / projects / commitments / follow_ups / meetings / personal_items)
  |
  v
Cross-reference: write resolved IDs onto the email as entities_referenced
  |
  v
Classification metadata (goal_pillar, label_applied, confidence) stored on the email
  |
  v
(existing, unchanged) Reply Draft Generation -> Meeting Detection (calendar_actions)
```

## 2. Layer Boundary (binding definition for this feature)

- **Knowledge layer** (existing, unmodified): `knowledge_items` / `context_snapshots` —
  thread-scoped facts and evolving context derived from messages (e.g. "has_pain_point:
  Pricing"). Not canonical, not deduplicated across real-world identity, not touched by
  this feature.
- **Canonical Entity layer** (new): `people`, `projects`, `commitments`, `follow_ups`,
  `meetings`, `personal_items` — persistent records representing real-world People,
  Projects, Commitments, FollowUps, Meetings, and PersonalItems, each with a canonical ID,
  resolved/deduplicated across threads and across time.
- **Email** = a source record. It never embeds entity data — it only references canonical
  entities by ID, via `entities_referenced`.
- **Classification metadata** (`goal_pillar`, `label_applied`, `confidence`) = plain fields
  on the email document. Explicitly **not** entities, not stored in any canonical
  collection.

## 3. Canonical Entity Types and ID Prefixes

| Entity | Prefix | Collection |
|---|---|---|
| Person | `PER-` | `people` |
| Project | `PRJ-` | `projects` |
| Commitment | `COM-` | `commitments` |
| FollowUp | `FU-` | `follow_ups` |
| Meeting | `MTG-` | `meetings` |
| PersonalItem | `PSN-` | `personal_items` |

These are the only six canonical entity types. No seventh "Record" entity is introduced.

`record_id` (an email-level field, see §5) is **not** a canonical entity ID — it is simply
an alias of the email's existing `message_id`, with no independent generation, prefix, or
collection of its own.

IDs are generated via one shared, infrastructure-only collection:

```text
counters: { "_id": "<prefix>", "seq": <int> }
```

`next_id(db, prefix) -> str` atomically increments `seq` via `find_one_and_update` with
`$inc` and returns `f"{prefix}{seq:03d}"` (e.g. `PER-042`). If `seq` exceeds 999 the id
grows to 4+ digits (`PER-1000`) rather than erroring — no artificial cap.

## 4. Data Model

### 4.1 `emails` (existing collection — new fields only)

| Field | Type | Notes |
|---|---|---|
| `record_id` | `str` | **Alias of `message_id`.** Same value, always. Not a new ID scheme. |
| `source_type` | `str` | Constant `"gmail"` — the only source this project supports. |
| `source_link` | `str \| None` | See §7.3 — only populated when `message_id` matches Gmail's internal 16-hex-char ID shape; otherwise `None`. |
| `date` | `str` | Calendar date only (`YYYY-MM-DD`), derived from `timestamp` — no new extraction. |
| `entities_referenced` | `dict` | `{"people": [...], "projects": [...], "commitments": [...], "follow_ups": [...], "meetings": [...], "personal": [...]}` — lists of canonical IDs. Empty lists when nothing resolved. |
| `goal_pillar` | `str` | Classification metadata, from the LLM analysis. |
| `label_applied` | `str` | One of the five labels in §9. |
| `confidence` | `float` | Classification confidence, from the LLM analysis. |

(`message_id`, `thread_id` (already derivable via `threads`), `from`, `to`, `cc`,
`subject`, `timestamp` already exist and are unchanged.)

### 4.2 `people`

`id, name, email, aliases, org, type, goal_pillar, role_in_pillar, tier, voice_register, last_inbound, last_outbound, reports_to, open_threads, note_link, review_flag, source`

`reports_to` is another Person's `id` (or `None`). `open_threads` is a list of `thread_id`s.
`review_flag: bool` — set `true` when this Person was created from an ambiguous
name-only match (see §8.1) rather than a confident email match. `source` is a constant
`"gmail"` for now.

### 4.3 `projects`

`id, project, cluster, entity, goal_pillar, objective, target, status, owner, collaborators, next_milestone, due, health, last_movement, note_link, source`

`owner`/`collaborators` are Person `id`s. `entity` is the org/company this project
belongs to. **No `review_flag` field** — per explicit instruction, the Project model is
not extended beyond this list.

### 4.4 `commitments`

`id, what, class, importance, owed_by, owed_to, source_record, made_on, committed_date, date_type, status, goal_pillar, project_id`

`class` is aliased exactly like `Email.from_`/`"from"` already is in this codebase (a
Python-reserved word aliased via Pydantic `Field(alias="class")`, `populate_by_name=True`),
one of `mine | owed_to_me | theirs | recap`. `date_type` is one of
`stated | inferred | window` (see §7.2). `source_record` is the triggering email's
`message_id`. `project_id` is a Project `id` or `None`.

### 4.5 `follow_ups`

`id, commitment_id, thread_id`

**Trimmed to exactly this** — your original spec for FollowUp never asked for a `status`
field; my first draft invented one by borrowing `ReplyDraft`/`CalendarAction`'s vocabulary
without justification, and that was wrong. Exactly one of `commitment_id` / `thread_id` is
set per record.

### 4.6 `meetings`

`id, date, attendees, project_or_pillar, minutes_record, actions_raised, next_meeting_date, agenda_target, agenda_written, actionable`

Distinct from the existing `calendar_actions` collection (see §2 of the prior design
discussion, restated in §10.4 below) — this is a record of a meeting the email *talks
about* (minutes, actions raised), not a proposal to schedule one.

`actionable: bool` is the **one field added by the relative-date meeting/action
requirement** (§5.4) — the only new field this change introduces, and explicitly
justified by that requirement: it distinguishes a future-oriented meeting mention ("we
will meet in 2 weeks") from a historical one ("we met last week"), which nothing else in
this schema could otherwise represent. `actionable = not raw_meeting.is_past` — true
whenever the LLM did not flag the mention as past-tense, regardless of whether a precise
date or only a vague window was resolved.

### 4.7 `personal_items`

`id, type, description, date_or_deadline, status`

### 4.8 `counters`

`{ "_id": "<prefix>", "seq": <int> }` — infrastructure only, never exposed through any
tool or API, exists purely to make ID generation atomic.

## 4.9 Indexes

Added to `app/database/indexes.py`, alongside the existing ones:

```python
db.people.create_index("id", unique=True)
db.people.create_index("email", unique=True, sparse=True)  # sparse: many People have no email
db.projects.create_index("id", unique=True)
db.commitments.create_index("id", unique=True)
db.commitments.create_index("thread_id")  # query performance only, not unique
db.follow_ups.create_index("id", unique=True)
db.follow_ups.create_index("commitment_id", sparse=True)
db.follow_ups.create_index("thread_id", sparse=True)
db.meetings.create_index("id", unique=True)
db.meetings.create_index("thread_id")
db.personal_items.create_index("id", unique=True)
```

No index is added on `_id`/`seq` in `counters` — MongoDB already uniquely indexes `_id` by
default.

## 5. Deterministic Extraction vs. LLM Semantic Extraction vs. Canonical Resolution

Three strictly separate stages, with an explicit statement of what each can and cannot
touch:

| Stage | Can access MongoDB? | Can call the LLM? | Module |
|---|---|---|---|
| Deterministic extraction | No | No | `app/entities/extraction.py`, `app/entities/dates.py` |
| LLM semantic extraction | No | Yes (one call, reusing the existing `analyze_email` call — no new API call added) | `app/analysis/schemas.py` (extended `EmailAnalysis`), `app/providers/llm/*.py` |
| Canonical resolution | Yes (reads/writes `people`/`projects`/.../`counters`) | No | `app/entities/resolution.py` |

### 5.1 Deterministic extraction

Pure functions, no side effects:
- Names/emails/domains from the email's own structured `from`/`to`/`cc` fields (already
  parsed), plus a plain regex scan of the body for any additional email addresses (e.g. a
  signature block naming a different contact). Domains are derived by splitting found
  email addresses on `@`.
- `thread_id` — unchanged, via the existing `resolve_thread_id`.
- Date-phrase resolution — a **new, independent** implementation in `app/entities/dates.py`
  (weekday/"tomorrow"/explicit-date parsing), conceptually similar to
  `app/calendar/detector.py`'s private helpers but not importing or modifying that module,
  to avoid coupling two independent subsystems or risking existing meeting-detection
  tests. Given a raw phrase (from the LLM stage, see below) and the email's `timestamp` as
  reference, produces an actual date plus a classification: `stated` (an explicit calendar
  date found directly in text), `inferred` (a relative phrase like "next Friday" resolved
  via weekday math), or `window` (a vague phrase like "end of month" that cannot be pinned
  to one day — resolved to `None` with `date_type="window"`, never fabricated).

Deterministic extraction does **not** attempt to recognize a person's name mentioned only
in body prose (e.g. "our VP of Sales, Sarah") — that requires semantic understanding and is
explicitly the LLM stage's job, not regex's.

**Reference date, corrected:** date-phrase resolution (and a `Commitment`'s `made_on`) use
the *email's own* `timestamp` as the reference point — not wall-clock "now" at processing
time — matching the existing `detect_meeting`'s established pattern
(`app/calendar/detector.py:69`, called with `email.timestamp` from `app/pipeline.py`,
untouched by this feature). An earlier draft of this spec incorrectly used
`datetime.now(timezone.utc)`; corrected here before implementation.

`app/entities/dates.py` additionally exposes `find_date_phrase(text: str) -> str | None`,
scanning a body for the first recognizable date-related expression (explicit date,
"tomorrow", a weekday, a relative duration like "in 2 weeks"/"in 10 days", or a vague
window like "next month") and returning the matched substring verbatim. This is the single
source of date-phrase patterns — `MockLLMProvider` calls it directly (§5.2) rather than
maintaining a second, divergent set of regexes, so the phrase a mention carries and the
phrase `resolve_date_phrase` later resolves are guaranteed to come from the same pattern
set.

### 5.1.1 Relative-Date Meeting/Action Detection (added requirement)

`resolve_date_phrase` gains two additional recognized forms, in this priority order after
the existing explicit-date/tomorrow/weekday checks:

1. **Relative duration** — `"in {N} day(s)/week(s)"`, where `{N}` is a digit or a spelled
   number word ("two", "ten", ...) — resolves to `reference_now + timedelta(days=N or N*7)`,
   classified `inferred`. Example: email dated 2026-09-17, phrase "in 2 weeks" →
   2026-10-01.
2. **Vague window** — `"next month"`, `"sometime"`, `"end of (the) month"` — recognized
   explicitly (not merely falling through to an unnamed default) but resolves to `(None,
   "window")`, exactly like the existing generic vague-phrase handling.

**Meeting/action intent no longer requires an explicit calendar invitation.** The trigger
vocabulary is broadened from `meet|call|sync` to also recognize the noun forms
`meeting|meetings` and the phrase `catch up` — "The meeting is in 10 days" and "Let's catch
up in 10 days" must be detected, not only imperative "let's meet" phrasing.

**Historical mentions must not be treated as actionable.** `RawMeeting.is_past` (already
part of the schema, previously unused by resolution) now drives the new
`Meeting.actionable` field (§4.6): `actionable = not is_past`. For `MockLLMProvider`
specifically, "we met last week" is additionally never even recognized as a meeting
mention at all, because its trigger pattern matches the word "meet", not "met" — a second,
independent reason the historical case produces no actionable signal, on top of the
`is_past` mechanism a real LLM would set.

**Correction to the FollowUp rule (§6):** an earlier draft of this spec had `_process_entities`
create a thread-scoped `FollowUp` automatically whenever a meeting or personal item existed
with no commitment. That directly contradicts the already-approved principle that a
`FollowUp` is only ever derived from a resolved `Commitment` — it is removed before
implementation. A `Meeting` (actionable or not) never causes a `FollowUp` to be created by
itself.

### 5.2 LLM semantic extraction

`app/analysis/schemas.py`'s `EmailAnalysis` gains new optional fields, populated by the
same single `analyze_email` call every provider already makes (no second API call):

```python
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

# added to EmailAnalysis:
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

All new fields default to empty/neutral values, so this is backward compatible with every
existing test that constructs `EmailAnalysis` without them.

**The LLM never emits a canonical ID.** Its output is purely descriptive (names, hinted
org, raw date phrases, class/importance labels). `ClaudeProvider`'s (and, for interface
parity, `OpenAIProvider`'s) prompt is extended to ask for these fields; `MockLLMProvider`
gets new deterministic keyword-based logic so tests never need a real API call.

### 5.3 Canonical resolution

`app/entities/resolution.py` — deterministic application logic. Reads the `EmailAnalysis`
output plus the deterministic extraction results, and for each mentioned item either
matches it to an existing canonical entity or creates a new one via `next_id`. Never calls
the LLM. This is the **only** place a canonical ID is assigned or matched.

## 6. Resolution / Merge Rules

| Entity | Merge rule | On insufficient confidence |
|---|---|---|
| **Person** | Exact match on normalized `email` only. | **Never** merge on name similarity alone, under any threshold — always create a new `Person` with `review_flag=true`. This is a hard rule, not a scored threshold: without an email anchor there is no reliable way to prove it's the same real person. |
| **Project** | Exact normalized `project` name **within the same `entity` (org)**, plus at least one corroborating signal (matching `goal_pillar`, or thread/collaborator overlap). `entity` alone is never sufficient. | Create a new `Project`. No fuzzy-matching tier and no `review_flag` — per explicit instruction not to invent a Project review workflow or additional fields, fuzzy resolution for Project is deferred rather than built without a place to route uncertain matches. |
| **Commitment** | Exact match within the same `thread_id`: normalized `what` text + same `class` + same `committed_date`. Compared in Python against the thread's existing commitments (same approach as `app/knowledge/deduplication.py`'s exact-match step) — no new derived field persisted for this. | Create a new `Commitment`. |
| **Meeting** | Exact match within the same `thread_id` + same `date`. | Create a new `Meeting`. |
| **PersonalItem** | Exact match within the same sender email + normalized `description`. | Create a new `PersonalItem`. |
| **FollowUp** | Derived 1:1, **only** immediately after a `Commitment` resolves — `commitment_id` set to that commitment's id, `thread_id` left `None`. **A `Meeting` or `PersonalItem` never triggers a `FollowUp` by itself**, regardless of `actionable` status (see §5.1.1 correction) — the schema still permits a `thread_id`-only `FollowUp` for a future, deliberately-invoked case, but no code path in this pipeline creates one automatically today. Not independently deduplicated (it inherits idempotency from its commitment). | N/A |

No entity type ever performs a fuzzy-then-LLM-tiebreak resolution (unlike the existing
`knowledge_items` dedup) — every resolution above is fully deterministic.

## 7. `source_link` — verified, not assumed

`message_id` values observed from real Gmail traffic (e.g. `1a08090646ebaa45`) match
Gmail's internal 16-lowercase-hex-character message ID shape, for which
`https://mail.google.com/mail/u/0/#all/{id}` is a known deep-link pattern. However, the
`process_email` tool's own docstring tells Claude it may supply *either* that internal ID
*or* an RFC-822 `Message-ID` header — and this project has no way to force which one
arrives, nor a live Gmail account to verify the link against. To avoid emitting a
plausibly-wrong URL: `source_link` is only constructed when `message_id` matches
`^[0-9a-f]{16}$`; otherwise it is `None`. This is documented as a best-effort derivation,
not a verified guarantee.

## 8. Pipeline Integration

### 8.1 New stage placement

```
normalize → thread → LLM analysis → cumulative context → knowledge extraction/dedup
    → [NEW] entity extraction + resolution + classification
    → reply draft generation → meeting detection
```

Placed after knowledge processing (it consumes the same `EmailAnalysis` knowledge
processing already has) and before reply drafting (reply drafting does not depend on it).

### 8.2 `ProcessingStage` addition

`app/processing/models.py`'s `ProcessingStage` enum and `STAGE_ORDER` gain one new value,
`ENTITIES_PROCESSED`, inserted between `KNOWLEDGE_PROCESSED` and `REPLY_PROCESSED`.

### 8.3 Failure behavior

Reuses the pipeline's existing per-email `try/except` (already wraps every stage) — if
entity extraction/resolution raises, the email is marked `FAILED` with
`failed_stage=ENTITIES_PROCESSED`, exactly like every other stage. Already-persisted work
for that email (the email doc itself, its thread, context snapshot, knowledge items) is
**not** rolled back — consistent with the pipeline's existing non-transactional,
per-stage-tracked design. The batch continues to the next email.

### 8.4 Idempotency

Reprocessing an already-`COMPLETED` email is already skipped before threading/analysis
even starts (existing behavior) — so entity resolution never re-runs for a message that
was already fully processed, and never creates duplicate entities for the same
`message_id`. A *different* email in the same thread later resolving to the *same* Person
or Project is expected, normal entity evolution (e.g. updating a Person's `last_inbound`),
not a duplicate.

## 9. `entities_referenced` Write-Back

`EmailRepository` gains one new method, `set_entity_metadata(message_id, record_id, source_type, source_link, date, entities_referenced, goal_pillar, label_applied, confidence)`,
performing a single targeted `$set` update — the same pattern as the existing `set_stage`
method. The initial email insert (existing code, early in `run_pipeline`) is unchanged;
this is a follow-up update once resolution completes, called from the new pipeline stage.

## 10. What Remains Unaffected

- `app/pipeline.py`'s existing stages (validate/thread/analyze/context/knowledge/reply/meeting)
  keep their exact current logic — the new stage is inserted, nothing existing is
  rewritten.
- `knowledge_items` and `context_snapshots` — zero changes; `_process_knowledge` and
  `build_next_context` are untouched.
- `reply_drafts` and `calendar_actions` — zero changes; `needs_reply`/`draft_reply` and
  `detect_meeting`/`build_calendar_action` are untouched. The new `meetings` collection is
  a separate, additional record — it does not replace or feed into `calendar_actions`.
- Every existing test in `tests/` continues to pass unmodified (verified in the
  implementation plan's tasks via a full-suite run after each task).

## 11. Testing Requirements

- Deterministic extraction: names/emails/domains parsed correctly from headers and a body
  signature block; date-phrase resolution for explicit dates, relative weekday phrases, and
  vague "window" phrases (each producing the correct `date_type`).
- Canonical ID generation: sequential, correctly prefixed, atomic under repeated calls,
  never collides across prefixes.
- Exact email/person matching: two mentions of the same email merge into one `Person`;
  fields like `last_inbound` update on the existing record rather than creating a
  duplicate.
- Ambiguous person names: two mentions of the same *name* with *no* email present create
  two separate `Person` records, both `review_flag=true` — never silently merged.
- Project resolution: same name + same `entity` + corroborating signal merges; same name
  under a *different* `entity` does not; a same-org, same-name project *without* any
  corroborating signal does not merge either (per §6's "entity alone is never sufficient").
- Commitment deduplication: reprocessing an identical commitment (same thread/what/class/date)
  does not create a duplicate; a differing `committed_date` does create a new one.
- FollowUp relationships: a `FollowUp` is created with `commitment_id` set when derived from
  a commitment, and with `thread_id` set (not `commitment_id`) when derived without one —
  never both, never neither.
- Email cross-references: after processing, the email's `entities_referenced` contains
  exactly the IDs of the entities that were actually resolved for it — no extras, no
  omissions.
- Pipeline failure handling: a simulated failure during the new stage marks the email
  `FAILED` at `failed_stage=ENTITIES_PROCESSED` without rolling back already-persisted
  knowledge/context/thread data, and the batch continues to the next email.
- MongoDB indexes: `people.email` is a sparse unique index (two Persons with no email can
  coexist; two Persons cannot share the same non-null email); every new collection has a
  unique index on `id`.
- Relative-date meeting/action detection (§5.1.1): each of "we will meet in 2 weeks",
  "let's meet next Friday", "we can meet tomorrow", "the meeting is in 10 days" resolves a
  correct date/date-type and `actionable=true`; a meeting mention with zero commitments
  present still resolves correctly; an email containing both a commitment and a
  relative-date meeting produces both entities with exactly one `FollowUp` (from the
  commitment only); "we met last week" produces no actionable meeting signal.

## 12. Explicit Design Decisions / Assumptions (flagged, not unilateral)

1. `EmailAnalysis` is extended in place (one LLM call) rather than adding a second LLM
   call — minimizes cost and API round-trips, per the explicit "don't unnecessarily use the
   LLM" instruction, while keeping resolution logic itself entirely separate and
   LLM-free.
2. Commitment/Meeting/PersonalItem dedup comparison happens by querying the thread's
   existing records and comparing normalized text in Python (mirroring
   `app/knowledge/deduplication.py`'s existing pattern) rather than via a MongoDB compound
   unique index — avoids persisting an extra derived field (e.g. a `what_normalized`
   column) that was never part of the requested schema.
3. Project resolution has no fuzzy-matching tier in this iteration (see §6) — an explicit,
   named simplification resulting from the "no Project review_flag, no extra fields"
   instruction, not an oversight.
4. `source_link` is best-effort and may be `None` for a real Gmail message if the incoming
   `message_id` is not in Gmail's internal-ID shape (see §7) — not independently verified
   against a live Gmail account.
5. `people`/`projects`/etc. are **not** thread-scoped (unlike `knowledge_items`) — a Person
   or Project persists and accumulates state across every thread it's resolved in, which is
   the entire point of a "canonical" entity layer.
