"""Streamlit entrypoint for the CoS Sales Agent human-in-the-loop dashboard.

Run with: `streamlit run app/ui/dashboard.py`

This is the only place in the system where "send email" and "create calendar
event" actions are actually triggered. Those side effects are reached
exclusively through the explicit Approve-button handlers in
`_render_reply_approval_tab` (via `simulate_send`) and
`_render_calendar_approval_tab` (via `approve_calendar_action`) — no other
code path in this module calls into the email/calendar providers.
"""

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
