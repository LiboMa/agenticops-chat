"""Root conftest: --run-integration flag (integration tests skipped by default) and the unit-test guards."""

import subprocess
import warnings

import pytest


def _block_live_bedrock_runtime() -> None:
    """Make every LIVE Bedrock runtime request fail fast for the rest of this process.

    Unit tests must never reach a real model. Without this, a background agent thread — e.g. the
    auto-execute an auto-approved fix plan spawns — runs a REAL agent: real cost, an interpreter exit
    that hangs while the call is in flight, and tool calls against whatever database
    settings.database_url points at by then. The guard sits at botocore's HTTP step, which is reached
    only when no before-call hook (Stubber) answered, so stubbed and mocked clients are untouched and
    other services pass through. It is never undone: daemon threads can outlive the session.
    """
    from botocore.client import BaseClient

    if getattr(BaseClient._make_request, "_aiops_live_model_guard", False):
        return
    real_make_request = BaseClient._make_request

    def _guarded_make_request(self, operation_model, request_dict, request_context):
        if self.meta.service_model.service_name == "bedrock-runtime":
            raise RuntimeError(
                f"Live Bedrock runtime call {operation_model.name} blocked in unit tests — "
                "mock the agent, the model or the client, or run with --run-integration"
            )
        return real_make_request(self, operation_model, request_dict, request_context)

    _guarded_make_request._aiops_live_model_guard = True
    BaseClient._make_request = _guarded_make_request


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
    if not config.getoption("--run-integration"):
        _block_live_bedrock_runtime()


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
