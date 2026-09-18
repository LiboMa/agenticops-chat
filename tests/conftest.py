"""Root conftest: registers --run-integration CLI flag and skips integration tests by default."""

import subprocess
import warnings

import pytest


def pytest_configure(config):
    """Warn if untracked test files exist — they inflate test counts."""
    result = subprocess.run(
        ["git", "status", "--short", "tests/"],
        capture_output=True, text=True, timeout=5
    )
    untracked = [l for l in result.stdout.splitlines() if l.startswith("??")]
    if untracked:
        warnings.warn(
            f"⚠️ {len(untracked)} untracked file(s) in tests/ — counts may be inflated:\n"
            + "\n".join(untracked[:5]),
            stacklevel=1,
        )


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
def _command_ledger_off(monkeypatch):
    """Keep the tool-layer command ledger (command_audits) OFF unless a test opts in.

    Under pytest settings.database_url is whatever .env says — the developer's real database —
    and the run_aws_cli / run_on_host / run_kubectl / run_skill_script tests have no DB fixture,
    so recording their fake attempts would append rows to a REAL audit ledger. Tests that assert
    on the ledger (tests/test_command_audit.py) point database_url at a tmp file and re-enable it.
    """
    from agenticops.config import settings

    monkeypatch.setattr(settings, "command_audit_enabled", False)
