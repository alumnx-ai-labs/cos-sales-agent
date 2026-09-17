from app.providers.llm.claude import _ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_mention_entity_signal_fields():
    for expected in [
        "people_mentioned",
        "projects_mentioned",
        "commitments_mentioned",
        "meetings_mentioned",
        "personal_items_mentioned",
        "goal_pillar",
        "label_applied",
        "confidence",
    ]:
        assert expected in _ANALYSIS_INSTRUCTIONS


def test_analysis_instructions_do_not_ask_the_llm_for_canonical_ids():
    lowered = _ANALYSIS_INSTRUCTIONS.lower()
    assert "per-" not in lowered
    assert "prj-" not in lowered
    assert "canonical id" not in lowered
