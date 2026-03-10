"""Root conftest: registers --run-integration CLI flag, skips integration tests,
and ensures DB engine isolation between test modules.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require live AWS credentials",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="Need --run-integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def _reset_db_engine():
    """Reset the shared SQLAlchemy _engine singleton before each test.

    Multiple test files create their own tmp_path SQLite DBs and set
    settings.database_url, but the models module caches a singleton _engine.
    Without this reset, a test that runs after another module may inherit
    a stale engine pointing to a deleted tmp DB file, causing
    ObjectDeletedError / NoneType cascades.
    """
    yield
    try:
        import agenticops.models as models_mod
        models_mod._engine = None
    except Exception:
        pass
