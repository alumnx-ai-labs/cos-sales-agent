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
