from pathlib import Path

import mongomock
import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.database.indexes import initialize_indexes  # noqa: E402

# AppTest.from_file() resolves a relative path against the directory of the
# file that *calls* it (this test file's directory), not the process cwd, so
# a bare "app/ui/dashboard.py" does not resolve to the repo's app/ui/dashboard.py.
# Build an absolute path instead.
DASHBOARD_SCRIPT = Path(__file__).resolve().parent.parent / "app" / "ui" / "dashboard.py"


def test_dashboard_app_runs_without_exceptions(monkeypatch):
    fake_client = mongomock.MongoClient()
    initialize_indexes(fake_client["cos_sales_test"])

    monkeypatch.setenv("EMAIL_PROVIDER", "demo")
    monkeypatch.setenv("CALENDAR_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MONGODB_DATABASE", "cos_sales_test")

    # Patch get_client on its defining module rather than importing
    # app.ui.dashboard directly: the dashboard module calls main() at import
    # time (required so `streamlit run app/ui/dashboard.py` works), so a bare
    # `import app.ui.dashboard` here would execute the real app against a
    # real MongoDB connection before we get a chance to patch anything.
    # AppTest.from_file() execs the script fresh from source into its own
    # module namespace, re-resolving `from app.database.mongodb import
    # get_client` against the (already-imported, now-patched) mongodb
    # module, so patching it there is what actually takes effect during the
    # AppTest run.
    import app.database.mongodb as mongodb_module

    monkeypatch.setattr(mongodb_module, "get_client", lambda uri: fake_client)

    at = AppTest.from_file(str(DASHBOARD_SCRIPT))
    at.run()
    assert not at.exception
