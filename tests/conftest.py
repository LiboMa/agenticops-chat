"""Root conftest: --run-integration flag (integration tests skipped by default) and the unit-test guards."""

import os
import subprocess
import threading
import warnings

import pytest


def _block_live_bedrock_runtime() -> None:
    """Make every LIVE Bedrock runtime request fail fast for the rest of this process.

    Unit tests must never reach a real model. Without this, a background agent thread — e.g. the
    auto-execute an auto-approved fix plan spawns — runs a REAL agent: real cost, an interpreter exit
    that hangs while the call is in flight, and tool calls against whatever database
    settings.database_url points at by then. The guard wraps BaseClient._make_request, botocore's HTTP
    step, which is reached only when no before-call hook answered: a Stubber and client- or agent-level
    mocks never reach _make_request, so they are untouched, and other services pass through. An
    HTTP-layer mock of bedrock-runtime (a before-send hook, moto) sits BELOW the guard and is never
    reached: the guard raises first. It is never undone: daemon threads can outlive the session.
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


# One line per send the guard refused, listed by pytest_terminal_summary.
_BLOCKED_AWS_CALLS: list[str] = []


def _block_real_aws_http() -> None:
    """Make every real botocore HTTP send fail for the rest of this process.

    URLLib3Session.send is botocore's socket step, below every before-send hook: a Stubber, moto or a mocked
    client answers first and never reaches it, so only a request that would really leave the machine is
    refused. Each refusal is recorded with the running test and the thread, because the fire-and-forget
    notifier and upload threads swallow the error. It is never undone: daemon threads can outlive the session.
    """
    from botocore.httpsession import URLLib3Session

    if getattr(URLLib3Session.send, "_aiops_aws_guard", False):
        return

    def _blocked_send(self, request):
        call = f"real AWS call blocked in tests: {request.method} {request.url}"
        _BLOCKED_AWS_CALLS.append(f"{call} [test={os.environ.get('PYTEST_CURRENT_TEST', '-')} "
                                  f"thread={threading.current_thread().name}]")
        raise RuntimeError(call)

    _blocked_send._aiops_aws_guard = True
    URLLib3Session.send = _blocked_send


def pytest_configure(config):
    """Warn if untracked test files exist — they inflate test counts — and install the guards: the live-Bedrock
    one (_block_live_bedrock_runtime) unless --run-integration, the real-AWS send one (_block_real_aws_http)
    unless AIOPS_TESTS_ALLOW_AWS=1."""
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
    if os.environ.get("AIOPS_TESTS_ALLOW_AWS") != "1":  # the opt-out tests/integration needs for live AWS
        _block_real_aws_http()


def pytest_terminal_summary(terminalreporter):
    if _BLOCKED_AWS_CALLS:
        terminalreporter.section(f"{len(_BLOCKED_AWS_CALLS)} botocore send(s) refused by the test guard")
        for line in _BLOCKED_AWS_CALLS:
            terminalreporter.write_line(line)


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


@pytest.fixture(autouse=True)
def _fresh_uncovered_refusals():
    """save_execution_result refuses an uncovering result once per (plan, execution) — process-local state.
    Every test's database restarts ids at 1, so a refusal left by one test would change the next one's."""
    import sys

    mod = sys.modules.get("agenticops.tools.metadata_tools")
    if mod is not None:
        mod._UNCOVERED_REFUSED.clear()
    yield
