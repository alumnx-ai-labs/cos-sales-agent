from app.providers.email.mock import MockEmailProvider


def test_mock_email_provider_returns_configured_payloads_up_to_limit():
    payloads = [{"message_id": f"msg_{i}"} for i in range(5)]
    provider = MockEmailProvider(payloads)

    assert provider.fetch_emails(limit=3) == payloads[:3]
    assert provider.fetch_emails(limit=100) == payloads


def test_mock_email_provider_send_email_does_not_raise(capsys):
    provider = MockEmailProvider([])
    provider.send_email(to="john@example.com", subject="Re: Hi", body="Body")
    captured = capsys.readouterr()
    assert "[SIMULATED EMAIL SEND]" in captured.out
