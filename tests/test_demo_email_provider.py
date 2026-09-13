from app.providers.email.demo import DemoEmailProvider


def test_demo_email_provider_respects_limit():
    provider = DemoEmailProvider(seed=42)
    assert len(provider.fetch_emails(limit=3)) == 3


def test_demo_email_provider_is_deterministic_across_instances():
    first = DemoEmailProvider(seed=42).fetch_emails(limit=50)
    second = DemoEmailProvider(seed=42).fetch_emails(limit=50)
    assert first == second


def test_demo_email_provider_send_email_prints_simulated_marker(capsys):
    provider = DemoEmailProvider(seed=42)
    provider.send_email(to="a@example.com", subject="s", body="b")
    assert "[SIMULATED EMAIL SEND]" in capsys.readouterr().out
