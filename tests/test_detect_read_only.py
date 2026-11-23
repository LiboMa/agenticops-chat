"""A detection run only reads, in code (MVP-2.9.0 N31).

Found while planning the issue reset of 2026-11-23: the detect agent's account-bound cloud CLI tool ran every command
it could not call a read — N30 had made the diagnosis and the fix-plan run read-only, not the detection. A detection
writes nothing but the issues it opens (create_health_issue, the platform's own database).

There are three ways into a detection: detect_agent() (Main's tool, the CLI, schedules), the parallel per-account
checker that POST /api/health-check and the scan agent call directly, and detect_agent()'s own single-account path.
The flag is set where the model is called: in checker.engine._check_one_account (each worker thread) and around the
single-account invoke.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from strands import Agent

from agenticops.models import CommandAudit, get_session
from agenticops.run_context import get_run_context, run_context
from agenticops.services.command_audit import change_context_refusal
from tests.test_run_guard import Scripted
from tests.test_viewer_role import _temp_db


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "n31.db")
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    s = get_session()
    yield s
    s.close()


def _rows(db):
    db.expire_all()
    return [(r.tool, r.tier, r.outcome, r.reason) for r in db.query(CommandAudit).order_by(CommandAudit.id)]


def test_the_refusal_says_where_a_change_belongs_in_a_detection(ledger):
    with run_context(read_only_run="detect"):
        out = change_context_refusal(tool="provider_aws_cli", tier="write", command="aws ec2 stop-instances --instance-ids i-1")
    assert "a detection run" in out and "only reads" in out and "require_confirmation changes nothing" in out
    assert "issue" in out.split("If it would change something, ")[1]      # … it goes into the issue it opens
    assert _rows(ledger) == [("provider_aws_cli", "write", "refused", "read_only_run")]


# ── the parallel checker: POST /api/health-check, the scan agent, detect_agent() with several accounts ──────────

def _two_accounts():
    accounts = [SimpleNamespace(id=1, name="a1", provider="aws", regions=["eu-west-1"]),
                SimpleNamespace(id=2, name="a2", provider="aws", regions=["eu-west-1"])]
    provider = MagicMock()
    provider.sdk_session.return_value = MagicMock()
    return accounts, (lambda acct: (provider, MagicMock(name=f"cli-{acct.name}")))


def test_every_account_worker_is_a_read_only_run_and_the_caller_is_not():
    from agenticops.checker import check_accounts_parallel
    accounts, pair = _two_accounts()
    seen = []

    def invoke(agent, prompt, **kw):
        seen.append((prompt, get_run_context().read_only_run))
        return "Created 0 issues"

    with patch("agenticops.scanner.engine._load_accounts", return_value=accounts), \
            patch("agenticops.scanner.engine._get_provider_and_tool", side_effect=pair), \
            patch("agenticops.agents.detect_agent._build_detect_agent_for_account", return_value=MagicMock()), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke):
        result = asyncio.run(check_accounts_parallel(account_ids=[1, 2]))
    assert [flag for _prompt, flag in seen] == ["detect", "detect"]
    assert len(result.accounts) == 2 and not any(a.errors for a in result.accounts)
    assert get_run_context().read_only_run is None


def test_what_a_workers_model_confirms_for_itself_is_not_sent(ledger):
    from agenticops.checker.engine import _check_one_account
    from agenticops.tools.aws_cli_tool import run_aws_cli
    acct = SimpleNamespace(id=1, name="a1", provider="aws", regions=["eu-west-1"])
    built = {}

    def build(**kwargs):
        built["agent"] = Agent(model=Scripted([[("run_aws_cli", {"command": "aws ec2 create-tags --resources i-1 --tags Key=a,Value=b",
                                                                 "require_confirmation": True})], "Created 0 issues"]),
                               tools=[run_aws_cli], callback_handler=None)
        return built["agent"]

    with patch("agenticops.agents.detect_agent._build_detect_agent_for_account", side_effect=build), \
            patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)
    assert not ex.called and not result.errors
    assert _rows(ledger) == [("run_aws_cli", "write", "refused", "read_only_run")]
    [answer] = [b["toolResult"] for m in built["agent"].messages for b in m["content"] if "toolResult" in b]
    assert "a detection run" in answer["content"][0]["text"]
    assert get_run_context().read_only_run is None


def test_a_worker_that_fails_leaves_no_flag_behind():
    from agenticops.checker.engine import _check_one_account
    acct = SimpleNamespace(id=1, name="a1", provider="aws", regions=[])
    with patch("agenticops.agents.detect_agent._build_detect_agent_for_account", return_value=MagicMock()), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=RuntimeError("model unavailable")):
        result = _check_one_account(acct, MagicMock(), MagicMock(), "all", False)
    assert result.errors == ["model unavailable"]
    assert get_run_context().read_only_run is None


# ── detect_agent()'s single-account path ─────────────────────────────────────

def test_the_single_account_detection_is_a_read_only_run(ledger):
    import importlib
    mod = importlib.import_module("agenticops.agents.detect_agent")    # the package re-exports the tool under this name
    from agenticops.tools.aws_cli_tool import run_aws_cli
    built = {}

    def agent_class(**kwargs):            # the real Agent, with the tools the code gave it and a scripted model
        built["agent"] = Agent(**{**kwargs, "model": Scripted([[("run_aws_cli", {
            "command": "aws ec2 create-tags --resources i-1 --tags Key=a,Value=b", "require_confirmation": True})],
            "Created 0 issues"]), "system_prompt": "p"})
        return built["agent"]

    with patch("agenticops.scanner.engine._load_accounts", return_value=[]), \
            patch.object(mod, "get_all_cli_tools", return_value=[run_aws_cli]), \
            patch.object(mod, "BedrockModel"), patch.object(mod, "Agent", side_effect=agent_class), \
            patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)), \
            patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
            patch("agenticops.services.agent_log_service.track_agent"), \
            patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
        out = mod.detect_agent(scope="all")
    assert "Created 0 issues" in out and not ex.called
    assert _rows(ledger) == [("run_aws_cli", "write", "refused", "read_only_run")]
    assert get_run_context().read_only_run is None


def test_outside_a_detection_the_same_worker_code_is_not_read_only():
    # the control: the flag comes from the worker, not from the test's setup
    seen = {}
    with patch("agenticops.agents.preamble.invoke_with_retry",
               side_effect=lambda agent, prompt, **kw: seen.setdefault("flag", get_run_context().read_only_run) or ""):
        from agenticops.agents.preamble import invoke_with_retry
        invoke_with_retry(MagicMock(), "x")
    assert seen["flag"] is None
