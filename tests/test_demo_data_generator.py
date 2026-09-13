from demo_data.generator import generate_demo_emails


def test_generate_demo_emails_is_deterministic_for_same_seed():
    first = generate_demo_emails(seed=42)
    second = generate_demo_emails(seed=42)
    assert first == second


def test_generate_demo_emails_covers_the_expected_narrative_beats():
    emails = generate_demo_emails(seed=42)
    bodies = " ".join(e["body"].lower() for e in emails)

    assert len(emails) >= 9
    assert "salesforce" in bodies  # competitor mention
    assert "pricing" in bodies  # pricing discussion
    assert any("seat" in e["body"].lower() for e in emails)  # seat-count requirement
    assert any(("meet" in e["body"].lower() or "call" in e["body"].lower()) for e in emails)  # meeting request


def test_generate_demo_emails_seat_count_changes_across_thread():
    emails = generate_demo_emails(seed=42)
    seat_mentions = [e["body"] for e in emails if "seat" in e["body"].lower()]
    assert any("100" in body for body in seat_mentions)
    assert any("150" in body for body in seat_mentions)


def test_generate_demo_emails_all_share_one_thread_id():
    emails = generate_demo_emails(seed=42)
    thread_ids = {e.get("thread_id") for e in emails}
    assert len(thread_ids) == 1
    assert None not in thread_ids
