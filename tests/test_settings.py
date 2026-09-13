import os
from app.config.settings import Settings, get_settings


def test_settings_load_defaults(monkeypatch):
    monkeypatch.delenv("EMAIL_LIMIT", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.email_limit == 50
    assert settings.email_provider == "demo"
    assert settings.calendar_provider == "mock"
    assert settings.llm_provider == "mock"
    assert settings.simulation_mode is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("EMAIL_LIMIT", "10")
    monkeypatch.setenv("EMAIL_PROVIDER", "mcp")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.email_limit == 10
    assert settings.email_provider == "mcp"
    get_settings.cache_clear()
