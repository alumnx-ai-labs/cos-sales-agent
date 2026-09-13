import pytest


@pytest.fixture(autouse=True)
def _isolated_settings_cache():
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
