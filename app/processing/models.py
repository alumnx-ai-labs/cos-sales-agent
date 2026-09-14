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
