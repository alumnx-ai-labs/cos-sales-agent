import pytest

from app.config.settings import Settings
from app.providers.calendar.mock import MockCalendarProvider
from app.providers.factory import ProviderFactory
from app.providers.llm.mock import MockLLMProvider


def test_factory_creates_demo_email_provider_by_default():
    from app.providers.email.demo import DemoEmailProvider

    settings = Settings(email_provider="demo")
    provider = ProviderFactory.create_email_provider(settings)
    assert isinstance(provider, DemoEmailProvider)


def test_factory_creates_mock_calendar_provider():
    settings = Settings(calendar_provider="mock")
    provider = ProviderFactory.create_calendar_provider(settings)
    assert isinstance(provider, MockCalendarProvider)


def test_factory_creates_mock_llm_provider():
    settings = Settings(llm_provider="mock")
    provider = ProviderFactory.create_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_factory_raises_on_unknown_provider_name():
    settings = Settings(llm_provider="not_a_real_provider")
    with pytest.raises(ValueError):
        ProviderFactory.create_llm_provider(settings)


def test_factory_raises_when_mcp_email_selected_but_not_enabled():
    settings = Settings(email_provider="mcp", mcp_email_enabled=False)
    with pytest.raises(ValueError, match="MCP_EMAIL_ENABLED"):
        ProviderFactory.create_email_provider(settings)


def test_factory_raises_when_mcp_calendar_selected_but_not_enabled():
    settings = Settings(calendar_provider="mcp", mcp_calendar_enabled=False)
    with pytest.raises(ValueError, match="MCP_CALENDAR_ENABLED"):
        ProviderFactory.create_calendar_provider(settings)


def test_factory_creates_mcp_email_provider_when_enabled():
    from app.providers.email.mcp import MCPEmailProvider

    settings = Settings(email_provider="mcp", mcp_email_enabled=True)
    provider = ProviderFactory.create_email_provider(settings)
    assert isinstance(provider, MCPEmailProvider)


def test_factory_creates_mcp_calendar_provider_when_enabled():
    from app.providers.calendar.mcp import MCPCalendarProvider

    settings = Settings(calendar_provider="mcp", mcp_calendar_enabled=True)
    provider = ProviderFactory.create_calendar_provider(settings)
    assert isinstance(provider, MCPCalendarProvider)
