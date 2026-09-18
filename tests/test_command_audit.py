"""Tool-layer command ledger + change_required refusal (MVP-2.6.0 S1)."""
from unittest.mock import patch

import pytest

from agenticops.models import Base, CommandAudit, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cmd.db"
    # tests/conftest.py keeps the ledger OFF for every test (the tool tests have no DB fixture
    # and would otherwise write to the developer's .env database); this file asserts on it.
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _rows(db):
    db.expire_all()
    return db.query(CommandAudit).order_by(CommandAudit.id).all()


class TestRecordCommand:
    def test_writes_row_with_run_context(self, db):
        from agenticops.services.command_audit import record_command
        with run_context(actor="cli:malibo", trace_id="TRC-aa", fix_plan_id=4, change_request_id=2, agent_name="executor"):
            record_command(tool="run_aws_cli", tier="write", command="aws ec2 create-tags --resources i-1",
                           outcome="executed", account="dev", region="ap-southeast-1", exit_code=0,
                           output_excerpt="{}", duration_ms=120)
        (row,) = _rows(db)
        assert (row.actor, row.trace_id, row.fix_plan_id, row.change_request_id, row.agent_name) == \
               ("cli:malibo", "TRC-aa", 4, 2, "executor")
        assert row.outcome == "executed" and row.exit_code == 0 and row.account == "dev"

    def test_redacts_secrets_and_caps_excerpt(self, db):
        from agenticops.services.command_audit import record_command
        # AWS's documented EXAMPLE access key id (never a real credential) — redact_secrets masks the AKIA… pattern
        record_command(tool="run_on_host", tier="write", command="aws configure set aws_access_key_id AKIAIOSFODNN7EXAMPLE",
                       outcome="executed", output_excerpt="x" * 5000)
        (row,) = _rows(db)
        assert "AKIAIOSFODNN7EXAMPLE" not in row.command
        assert len(row.output_excerpt) <= 2000

    def test_disabled_writes_nothing(self, db):
        from agenticops.config import settings
        from agenticops.services.command_audit import record_command
        with patch.object(settings, "command_audit_enabled", False):
            record_command(tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed")
        assert _rows(db) == []

    def test_fail_soft_when_db_broken(self, db):
        from agenticops.services import command_audit
        with patch.object(command_audit, "get_db_session", side_effect=RuntimeError("db down")):
            command_audit.record_command(tool="run_aws_cli", tier="write", command="aws x", outcome="executed")  # no raise


class TestChangeRequiredMatch:
    def test_default_policy_file_has_change_required(self):
        from agenticops.services.policy_engine import get_policy_engine
        eng = get_policy_engine(reload=True)
        assert eng.change_required_match("aws ec2 modify-security-group-rules --group-id sg-1") is not None
        assert eng.change_required_match("aws rds modify-db-instance --x") is not None
        assert eng.change_required_match("aws ec2 create-tags --resources i-1") is None
        assert eng.change_required_match("kubectl scale deployment/x --replicas=2") is None

    def test_validate_rejects_non_list(self):
        from agenticops.services.policy_engine import validate_policy
        assert validate_policy({"rules": [], "change_required": "aws rds modify-"})


def _approved_plan(db) -> int:
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s", status="approved")
    db.add(plan); db.commit()
    return plan.id


class TestRunAwsCliLedger:
    def test_write_without_confirmation_is_recorded_as_refused(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        out = run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b")
        assert "requires confirmation" in out
        (row,) = _rows(db)
        assert (row.outcome, row.reason, row.tier) == ("refused", "confirmation", "write")

    def test_blocked_is_recorded(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        run_aws_cli(command="aws ec2 terminate-instances --instance-ids i-1", require_confirmation=True)
        (row,) = _rows(db)
        assert row.outcome == "blocked"

    def test_readonly_is_not_recorded(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="{}"):
            run_aws_cli(command="aws ec2 describe-instances")
        assert _rows(db) == []

    def test_change_required_refused_outside_approved_plan(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        out = run_aws_cli(command="aws ec2 modify-security-group-rules --group-id sg-1", require_confirmation=True)
        assert "/change" in out and "change request" in out.lower()
        (row,) = _rows(db)
        assert (row.outcome, row.reason) == ("refused", "change_required")

    def test_change_required_allowed_inside_approved_plan(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        pid = _approved_plan(db)
        with run_context(actor="agent:executor", fix_plan_id=pid), \
             patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
            out = run_aws_cli(command="aws ec2 modify-security-group-rules --group-id sg-1", require_confirmation=True)
        assert out == "ok" and ex.called
        (row,) = _rows(db)
        assert (row.outcome, row.fix_plan_id) == ("executed", pid)

    def test_executed_write_records_exit_code(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="Error (exit code 254): boom"):
            run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b", require_confirmation=True)
        (row,) = _rows(db)
        assert row.outcome == "error" and row.exit_code == 254


class TestRunOnHostLedger:
    def test_write_refused_is_recorded(self, db):
        from agenticops.skills.execution import run_on_host
        out = run_on_host(host_id="i-1", command="systemctl restart nginx")
        assert "requires confirmation" in out
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.target) == ("run_on_host", "refused", "i-1")

    def test_change_required_shell_command_refused(self, db):
        from agenticops.skills.execution import run_on_host
        out = run_on_host(host_id="i-1", command="systemctl restart nginx", require_confirmation=True)
        assert "/change" in out
        (row,) = _rows(db)
        assert row.reason == "change_required"

    def test_readonly_not_recorded(self, db):
        from agenticops.skills.execution import run_on_host
        with patch("agenticops.skills.execution._run_auto_ladder", return_value="ok"):
            run_on_host(host_id="i-1", command="df -h")
        assert _rows(db) == []


class TestRunKubectlLedger:
    """run_kubectl is isomorphic to run_on_host. The ledger stores the fully qualified
    `kubectl -n <ns> <cmd>`, but change_required is matched against `kubectl <cmd>` — the
    `-n <ns>` inserted between them would otherwise make `kubectl delete` unmatchable."""

    def test_change_required_refused_outside_approved_plan(self, db):
        from agenticops.skills.execution import run_kubectl
        out = run_kubectl(cluster_name="c1", command="delete pod x", require_confirmation=True)
        assert "/change" in out
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason, row.target) == ("run_kubectl", "refused", "change_required", "c1")
        assert row.command == "kubectl -n default delete pod x"

    def test_confirmed_write_is_recorded_as_executed(self, db):
        from agenticops.skills.execution import run_kubectl
        with patch("agenticops.skills.execution._execute_kubectl", return_value="deployment.apps/x scaled") as ex:
            out = run_kubectl(cluster_name="c1", command="scale deployment/x --replicas=2", namespace="prod",
                              require_confirmation=True)
        assert out == "deployment.apps/x scaled" and ex.called
        (row,) = _rows(db)
        assert (row.outcome, row.tier, row.command) == ("executed", "write", "kubectl -n prod scale deployment/x --replicas=2")

    def test_readonly_not_recorded(self, db):
        from agenticops.skills.execution import run_kubectl
        with patch("agenticops.skills.execution._execute_kubectl", return_value="NAME"):
            run_kubectl(cluster_name="c1", command="get pods")
        assert _rows(db) == []


class TestLedgerOutcome:
    """The transports return prose, not status codes; the ledger's executed|error is judged from it."""

    def test_transport_error_shapes(self):
        from agenticops.skills.execution import _ledger_outcome
        assert _ledger_outcome("SSH error (exit 1) to root@h: denied") == "error"
        assert _ledger_outcome("Command Failed. Error: boom") == "error"
        assert _ledger_outcome("kubectl error (exit 1): nope") == "error"
        assert _ledger_outcome("Error: Unknown method 'x'. Use 'auto', 'ssm', or 'ssh'.") == "error"
        assert _ledger_outcome("nginx reloaded") == "executed"

    def test_ssh_fallback_leg_decides(self):
        from agenticops.skills.execution import _ledger_outcome
        assert _ledger_outcome("SSM failed: SSM TargetNotConnected: x\nFalling back to SSH 10.0.1.5 ...\nuptime: 5 days") == "executed"
        assert _ledger_outcome("SSM failed: SSM TargetNotConnected: x\nFalling back to SSH 10.0.1.5 ...\n"
                               "SSH error (exit 255) to h: refused") == "error"
        assert _ledger_outcome("SSM failed: x\nSSH fallback unavailable: no ip") == "error"


class TestRunSkillScriptLedger:
    def _enable(self, monkeypatch):
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_enabled", True, raising=False)

    def test_run_is_recorded_with_script_tier(self, db, monkeypatch):
        from agenticops.skills import sandbox
        from agenticops.skills.sandbox import SandboxResult
        from agenticops.skills.tools import run_skill_script
        self._enable(monkeypatch)
        res = SandboxResult(exit_code=3, stdout="out", stderr="", truncated=False, duration_ms=7, isolation="none")
        monkeypatch.setattr(sandbox, "run_script", lambda *a, **k: res)
        out = run_skill_script("log-analysis", "parse.py", args="--x 1")
        assert "exit_code=3" in out
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.exit_code, row.target, row.command) == \
               ("run_skill_script", "script", "error", 3, "log-analysis", "log-analysis/parse.py --x 1")

    def test_refusal_is_recorded(self, db, monkeypatch):
        from agenticops.skills import sandbox
        from agenticops.skills.tools import run_skill_script
        self._enable(monkeypatch)

        def _refuse(*a, **k):
            raise RuntimeError("draft skill")

        monkeypatch.setattr(sandbox, "run_script", _refuse)
        out = run_skill_script("log-analysis", "parse.py")
        assert out.startswith("Sandbox refused")
        (row,) = _rows(db)
        assert (row.outcome, row.reason) == ("refused", "sandbox")


class TestProviderCliLedger:
    """AWSProvider.cli_tool() is what executor / SRE / RCA receive once an account is resolved
    (executor_agent → get_cli_tool_for_issue). It is NOT confirmation-gated, so the ledger and
    the change_required gate are its only write-tier controls. Everything the shared classifier
    does not call readonly is recorded — including a command the provider's own (narrower) block
    list lets through while `_classify_command` says blocked."""

    @staticmethod
    def _tool(monkeypatch, *, returncode=0, session=True):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from agenticops.providers.aws import AWSProvider
        acct = SimpleNamespace(id=1, name="dev", provider="aws", credentials={}, regions=["ap-southeast-1"], labels={})
        provider = AWSProvider(acct)
        sess = Mock()
        sess.get_credentials.return_value.get_frozen_credentials.return_value = SimpleNamespace(
            access_key="AKIAIOSFODNN7EXAMPLE", secret_key="x", token=None)  # AWS's documented EXAMPLE key, never real
        if session:
            provider._session = sess
        run = Mock(return_value=SimpleNamespace(returncode=returncode, stdout="{}", stderr="boom"))
        monkeypatch.setattr("agenticops.providers.aws.subprocess.run", run)
        return provider.cli_tool(), run, sess

    def test_executed_write_is_recorded(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch)
        out = tool("aws ec2 create-tags --resources i-1 --tags Key=a,Value=b")
        assert out == "{}" and run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.account, row.exit_code, row.fix_plan_id) == \
               ("run_aws_cli", "write", "executed", "dev", 0, None)
        assert row.command == "aws ec2 create-tags --resources i-1 --tags Key=a,Value=b"  # as asked, no --output json

    def test_change_required_refused_outside_approved_plan(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch)
        out = tool("aws ec2 modify-security-group-rules --group-id sg-1")
        assert "/change" in out and not run.called
        (row,) = _rows(db)
        assert (row.outcome, row.reason, row.tier, row.account) == ("refused", "change_required", "write", "dev")

    def test_change_required_allowed_inside_approved_plan(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch)
        pid = _approved_plan(db)
        with run_context(actor="agent:executor", fix_plan_id=pid):
            out = tool("aws ec2 modify-security-group-rules --group-id sg-1")
        assert out == "{}" and run.called
        (row,) = _rows(db)
        assert (row.outcome, row.fix_plan_id, row.actor) == ("executed", pid, "agent:executor")

    def test_readonly_is_not_recorded(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch)
        assert tool("aws ec2 describe-instances") == "{}" and run.called
        assert _rows(db) == []

    def test_nonzero_exit_records_error_with_exit_code(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch, returncode=254)
        out = tool("aws ec2 create-tags --resources i-1 --tags Key=a,Value=b")
        assert out == "Error (exit 254): boom"
        (row,) = _rows(db)
        assert (row.outcome, row.exit_code) == ("error", 254) and "boom" in row.output_excerpt

    def test_provider_blocked_is_recorded(self, db, monkeypatch):
        tool, run, _ = self._tool(monkeypatch)
        out = tool("aws ec2 terminate-instances --instance-ids i-1")
        assert out == "Error: Blocked dangerous pattern 'ec2 terminate-instances' in command." and not run.called
        (row,) = _rows(db)
        assert (row.tier, row.outcome, row.account) == ("blocked", "blocked", "dev")

    def test_classifier_blocked_but_provider_allowed_leaves_a_trace(self, db, monkeypatch):
        # Pre-existing gap (not fixed here): the provider's BLOCKED_PATTERNS lack the secret-revealing reads
        # that aws_cli_tool blocks, so this executes. The ledger must say so honestly: tier=blocked, executed.
        tool, run, _ = self._tool(monkeypatch)
        assert tool("aws secretsmanager get-secret-value --secret-id s") == "{}" and run.called
        (row,) = _rows(db)
        assert (row.tier, row.outcome) == ("blocked", "executed")

    @pytest.mark.parametrize("fault,reason,text", [
        ("no_session", "no_session", "no resolved session for account 'dev'"),
        ("credentials", "credentials", "failed to resolve credentials for account 'dev'"),
        ("timeout", "timeout", "Command timed out after 30s."),
        ("aws_cli_missing", "aws_cli_missing", "AWS CLI ('aws') not found on PATH."),
    ])
    def test_transport_failures_are_recorded_as_error(self, db, monkeypatch, fault, reason, text):
        import subprocess
        tool, run, sess = self._tool(monkeypatch, session=(fault != "no_session"))
        if fault == "credentials":
            sess.get_credentials.return_value.get_frozen_credentials.side_effect = RuntimeError("boom")
        elif fault == "timeout":
            run.side_effect = subprocess.TimeoutExpired(cmd="aws", timeout=30)
        elif fault == "aws_cli_missing":
            run.side_effect = FileNotFoundError("aws")
        out = tool("aws ec2 create-tags --resources i-1 --tags Key=a,Value=b")
        assert text in out
        (row,) = _rows(db)
        assert (row.outcome, row.reason, row.exit_code, row.tier) == ("error", reason, None, "write")
        assert text in row.output_excerpt
