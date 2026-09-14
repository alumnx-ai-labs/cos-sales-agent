import mongomock
import pytest

import main as main_module
from app.config.settings import Settings


@pytest.fixture(autouse=True)
def _patch_mongo_client(monkeypatch):
    fake_client = mongomock.MongoClient()
    monkeypatch.setattr(main_module, "get_client", lambda uri: fake_client)
    yield fake_client


def test_healthcheck_reports_ok_with_default_mock_demo_settings(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    exit_code = main_module.main(["--healthcheck"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "MongoDB connected" in output
    assert "System ready" in output


def test_demo_mode_populates_database(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMAIL_LIMIT", "9")
    exit_code = main_module.main(["--mode=demo"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "processed" in output.lower()


def test_reset_demo_requires_simulation_mode(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "false")
    monkeypatch.setenv("APP_ENV", "production")
    exit_code = main_module.main(["--reset-demo"])
    assert exit_code == 1
