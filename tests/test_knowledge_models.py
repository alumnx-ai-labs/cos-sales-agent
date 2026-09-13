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
