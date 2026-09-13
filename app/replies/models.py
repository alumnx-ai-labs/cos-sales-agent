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
