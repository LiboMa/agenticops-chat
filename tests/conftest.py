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
