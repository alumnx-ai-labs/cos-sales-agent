import os
from app.config.settings import Settings, get_settings


def test_settings_load_defaults(monkeypatch):
    # Force every var this test asserts a schema default for via an OS-level env var
    # override, not just delenv("EMAIL_LIMIT") -- Settings reads a .env FILE
    # (model_config's env_file=".env"), which is a separate source from the OS
    # environment: delenv only removes an OS env var and has no effect on a value that
    # only lives in the .env file (e.g. a developer's local LLM_PROVIDER=claude for real
    # API testing). Per pydantic-settings' precedence, OS env vars outrank the dotenv
    # file, so explicitly setting each one to its documented default is what actually
    # makes this test assert the schema's defaults regardless of local .env content.
    monkeypatch.setenv("EMAIL_LIMIT", "50")
    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("SIMULATION_MODE", "true")
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
