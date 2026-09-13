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
