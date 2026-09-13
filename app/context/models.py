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
