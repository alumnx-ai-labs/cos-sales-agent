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
