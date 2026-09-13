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
