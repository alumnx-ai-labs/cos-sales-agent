from app.context.models import ContextSnapshot, ProvenancedValue, ThreadContext


def test_thread_context_defaults_are_empty():
    context = ThreadContext()
    assert context.requirements == []
    assert context.company == {}
    assert context.summary == ""


def test_provenanced_value_requires_basis_literal():
    value = ProvenancedValue(value="100 seats", basis="stated", source_email_ids=["msg_001"])
    assert value.basis == "stated"


def test_context_snapshot_round_trip():
    snapshot = ContextSnapshot(
        thread_id="thread_001",
        context_version=1,
        triggering_email_id="msg_001",
        context=ThreadContext(summary="Evaluating CRM"),
        changes_from_previous_context=[],
        created_at="2026-09-13T10:30:00Z",
    )
    assert snapshot.context.summary == "Evaluating CRM"
