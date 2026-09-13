from app.context.diff import diff_context
from app.context.models import ProvenancedValue, ThreadContext


def test_diff_detects_added_requirement():
    previous = ThreadContext()
    new = ThreadContext(
        requirements=[ProvenancedValue(value="100 seats", basis="stated", source_email_ids=["msg_001"])]
    )
    changes = diff_context(previous, new, source_email_id="msg_001")
    assert len(changes) == 1
    assert changes[0].type == "ADDED"
    assert changes[0].field == "requirements"
    assert changes[0].detail == "100 seats"


def test_diff_detects_updated_scalar_field():
    previous = ThreadContext(pricing={"budget": "$50K"})
    new = ThreadContext(pricing={"budget": "$75K"})
    changes = diff_context(previous, new, source_email_id="msg_007")
    assert any(c.type == "UPDATED" and c.field == "pricing.budget" for c in changes)


def test_diff_detects_removed_item():
    previous = ThreadContext(
        objections=[ProvenancedValue(value="Price too high", basis="stated", source_email_ids=["msg_002"])]
    )
    new = ThreadContext()
    changes = diff_context(previous, new, source_email_id="msg_003")
    assert any(c.type == "REMOVED" and c.field == "objections" for c in changes)


def test_diff_is_empty_when_nothing_changed():
    context = ThreadContext(summary="Same summary")
    changes = diff_context(context, context, source_email_id="msg_001")
    assert changes == []
