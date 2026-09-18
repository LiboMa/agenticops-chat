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
               ("provider_aws_cli", "write", "executed", "dev", 0, None)
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
        assert (row.tool, row.tier, row.outcome, row.account) == ("provider_aws_cli", "blocked", "blocked", "dev")

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
        ("aws_cli_missing", "cli_missing", "AWS CLI ('aws') not found on PATH."),
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


class TestRecordCommandHardening:
    def test_truncates_string_columns_to_their_widths(self, db):
        # PostgreSQL raises DataError on overflow (SQLite does not); fail-soft would swallow it and the
        # command would run with NO row. Widths are those of models.CommandAudit.
        from agenticops.services.command_audit import record_command
        with run_context(actor="a" * 120, trace_id="T" * 30, agent_name="g" * 60, on_behalf_of="b" * 120):
            record_command(tool="t" * 40, tier="write-tier-x", command="aws x", outcome="executed",
                           account="c" * 150, region="x" * 40, target="d" * 250, reason="r" * 60)
        (row,) = _rows(db)
        assert (len(row.actor), len(row.trace_id), len(row.agent_name), len(row.on_behalf_of)) == (100, 20, 50, 100)
        assert (len(row.tool), len(row.tier), len(row.account), len(row.region), len(row.target), len(row.reason)) == \
               (30, 10, 100, 30, 200, 50)
        assert row.region == "x" * 30

    def test_broken_ledger_warns_once_then_debug(self, db, caplog, monkeypatch):
        import logging
        from agenticops.services import command_audit
        monkeypatch.setattr(command_audit, "_warned_once", False, raising=False)
        with patch.object(command_audit, "get_db_session", side_effect=RuntimeError("db down")), \
             caplog.at_level(logging.DEBUG, logger="agenticops.services.command_audit"):
            command_audit.record_command(tool="run_aws_cli", tier="write", command="aws x", outcome="executed")
            command_audit.record_command(tool="run_aws_cli", tier="write", command="aws y", outcome="executed")
        levels = [r.levelno for r in caplog.records if "command audit write failed" in r.getMessage()]
        assert levels == [logging.WARNING, logging.DEBUG]


class TestChangeRequiredNormalization:
    """Plain substring matching was bypassable by a global option, doubled whitespace or a wrapper."""

    @pytest.mark.parametrize("command", [
        "aws --profile p ec2 modify-security-group-rules --group-id sg-1",   # global option before the service
        "systemctl  restart nginx",                                          # doubled whitespace
        "kubectl --context prod delete pod x",                               # value-taking global option
        "sudo systemctl restart nginx",                                      # privilege wrapper (run_on_host)
        "aws --region=us-east-1 rds modify-db-instance --x",                 # --opt=value is a single token
    ])
    def test_bypass_probes_now_match(self, command):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) is not None

    def test_readonly_with_options_stays_unmatched(self):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match("aws ec2 describe-instances --region x") is None

    def test_normalize_for_policy(self):
        from agenticops.services.policy_engine import _normalize_for_policy
        assert _normalize_for_policy("kubectl -n prod delete pod x") == "kubectl delete pod x"
        assert _normalize_for_policy("sudo -u postgres systemctl restart pg") == "systemctl restart pg"
        assert _normalize_for_policy("aws --profile=p ec2 modify-x --group-id sg-1") == "aws ec2 modify-x sg-1"
        assert _normalize_for_policy("systemctl restart 'nginx") == "systemctl restart 'nginx"  # unbalanced quote → str.split


class TestGuardedRun:
    @staticmethod
    def _run(text="ok"):
        from unittest.mock import Mock
        return Mock(return_value=text)

    def test_readonly_runs_without_a_row(self, db):
        from agenticops.services.command_audit import guarded_run
        run = self._run()
        assert guarded_run(tool="provider_x", tier="readonly", command="x get", run=run,
                           outcome_of=lambda t: ("executed", 0)) == "ok"
        assert run.called and _rows(db) == []

    def test_change_required_refuses_before_running(self, db):
        from agenticops.services.command_audit import guarded_run
        run = self._run()
        out = guarded_run(tool="provider_x", tier="unknown", command="aws rds reboot-db-instance --x", run=run,
                          outcome_of=lambda t: ("executed", 0), account="acc", target="tgt")
        assert "/change" in out and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.reason, row.account, row.target) == \
               ("provider_x", "unknown", "refused", "change_required", "acc", "tgt")

    def test_change_required_runs_inside_approved_plan(self, db):
        from agenticops.services.command_audit import guarded_run
        pid = _approved_plan(db)
        run = self._run()
        with run_context(actor="agent:executor", fix_plan_id=pid):
            assert guarded_run(tool="provider_x", tier="unknown", command="aws rds reboot-db-instance --x", run=run,
                               outcome_of=lambda t: ("executed", 0)) == "ok"
        (row,) = _rows(db)
        assert (row.outcome, row.fix_plan_id) == ("executed", pid) and run.called

    def test_records_outcome_from_two_or_three_tuple(self, db):
        from agenticops.services.command_audit import guarded_run
        guarded_run(tool="provider_x", tier="write", command="x set a", run=self._run("done"),
                    outcome_of=lambda t: ("executed", 0), region="r1")
        guarded_run(tool="provider_x", tier="write", command="x set b", run=self._run("Error: Command timed out after 30s."),
                    outcome_of=lambda t: ("error", None, "timeout"))
        a, b = _rows(db)
        assert (a.outcome, a.exit_code, a.output_excerpt, a.region, a.reason) == ("executed", 0, "done", "r1", None)
        assert (b.outcome, b.exit_code, b.reason) == ("error", None, "timeout")


class TestCliOutcome:
    @pytest.mark.parametrize("text,expected", [
        ('{"ok": true}', ("executed", 0, "")),
        ("(no output)", ("executed", 0, "")),
        ("Error (exit 254): boom", ("error", 254, "")),
        ("Error (exit -1): Timed out after 60s", ("error", -1, "")),
        ("Error: Command timed out after 30s.", ("error", None, "timeout")),
        ("Error: Invalid command syntax: No closing quotation", ("error", None, "syntax")),
        ("Error: Azure CLI ('az') not found on PATH.", ("error", None, "cli_missing")),
        ("Error: no resolved session for account 'dev'; cannot run AWS CLI safely (refusing to use ambient credentials).",
         ("error", None, "no_session")),
        ("Error: failed to resolve credentials for account 'dev': boom", ("error", None, "credentials")),
    ])
    def test_shapes(self, text, expected):
        from agenticops.services.command_audit import cli_outcome
        assert cli_outcome(text) == expected


class TestGenericCliTier:
    @pytest.mark.parametrize("command,tier", [
        ("az vm list --resource-group rg", "readonly"),
        ("az network nsg rule show --name r", "readonly"),
        ("az storage account show-connection-string -n x", "readonly"),
        ("az vm start --name x", "unknown"),
        ("gcloud compute instances describe vm-1 --zone z", "readonly"),
        ("gcloud compute instances delete vm-1", "unknown"),
        ("aliyun ecs DescribeInstances --RegionId cn-hangzhou", "unknown"),  # CamelCase verb is not on the list → conservative
        ("aliyun ecs StopInstance --InstanceId i-1", "unknown"),
    ])
    def test_samples(self, command, tier):
        from agenticops.services.command_audit import generic_cli_tier
        assert generic_cli_tier(command) == tier


class TestSshProviderLedger:
    @staticmethod
    def _tool(monkeypatch, returncode=0):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from agenticops.providers.ssh import SSHProvider
        creds = {"host": "10.0.0.5", "username": "ops"}
        provider = SSHProvider(SimpleNamespace(id=1, name="idc-1", provider="ssh", credentials=creds, regions=[], labels={}))
        provider._cfg = dict(creds)
        run = Mock(return_value=SimpleNamespace(returncode=returncode, stdout="ok\n", stderr=""))
        monkeypatch.setattr("agenticops.providers.ssh.subprocess.run", run)
        return provider.cli_tool(), run

    def test_write_is_recorded(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        assert tool("systemctl reload nginx") == "ok\n" and run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.account, row.target, row.exit_code) == \
               ("provider_ssh", "write", "executed", "idc-1", "10.0.0.5", 0)

    def test_change_required_refused(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        out = tool("systemctl restart nginx")
        assert "/change" in out and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason) == ("provider_ssh", "refused", "change_required")

    def test_readonly_not_recorded(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        assert tool("df -h") == "ok\n" and run.called
        assert _rows(db) == []

    def test_blocked_is_recorded_with_unchanged_reply(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        out = tool("mkfs.ext4 /dev/sdb")
        assert out == "Error (exit -1): Command blocked by security policy: 'mkfs.ext4 /dev/sdb'" and not run.called
        (row,) = _rows(db)
        assert (row.tier, row.outcome, row.target) == ("blocked", "blocked", "10.0.0.5")


class TestKubernetesProviderLedger:
    @staticmethod
    def _tool(monkeypatch, returncode=0):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from agenticops.providers.kubernetes import KubernetesProvider
        creds = {"context": "prod"}
        provider = KubernetesProvider(SimpleNamespace(id=1, name="c1", provider="kubernetes", credentials=creds, regions=[], labels={}))
        provider._cfg = {**creds, "kubeconfig_path": "/dev/null"}
        run = Mock(return_value=SimpleNamespace(returncode=returncode, stdout="deployment.apps/x scaled\n", stderr=""))
        monkeypatch.setattr("agenticops.providers.kubernetes.subprocess.run", run)
        return provider.cli_tool(), run

    def test_write_is_recorded_fully_qualified(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        assert tool("scale deployment/x --replicas=2").startswith("deployment.apps/x scaled") and run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.target, row.command) == \
               ("provider_kubectl", "write", "executed", "prod", "kubectl scale deployment/x --replicas=2")

    @pytest.mark.parametrize("command,tier", [
        ("delete pod x", "write"),
        ("kubectl --context prod delete pod x", "unknown"),   # the classifier sees `--context …` first; the gate still matches
    ])
    def test_change_required_refused(self, db, monkeypatch, command, tier):
        tool, run = self._tool(monkeypatch)
        out = tool(command)
        assert "/change" in out and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason, row.tier) == ("provider_kubectl", "refused", "change_required", tier)

    def test_readonly_not_recorded(self, db, monkeypatch):
        tool, run = self._tool(monkeypatch)
        tool("get pods -A")
        assert run.called and _rows(db) == []


class TestGenericProviderLedger:
    """azure / gcp / alicloud share one shape: tier from generic_cli_tier, one tool name per provider."""

    PROVIDERS = {
        # module: (class, ledger tool, credentials, readonly cmd, write cmd, change_required pattern for the test)
        "azure": ("AzureProvider", "provider_azure_cli", {"subscription_id": "sub-1"},
                  "az vm list", "az vm start --name x", "az vm start"),
        "gcp": ("GCPProvider", "provider_gcp_cli", {"project_id": "p1"},
                "gcloud compute instances list", "gcloud compute instances stop vm-1", "gcloud compute instances stop"),
        "alicloud": ("AlicloudProvider", "provider_alicloud_cli", {},
                     None, "aliyun ecs StopInstance --InstanceId i-1", "aliyun ecs stopinstance"),
    }

    @classmethod
    def _tool(cls, monkeypatch, module, returncode=0):
        import importlib
        from types import SimpleNamespace
        from unittest.mock import Mock
        cls_name, _tool_name, creds, *_ = cls.PROVIDERS[module]
        mod = importlib.import_module(f"agenticops.providers.{module}")
        provider = getattr(mod, cls_name)(SimpleNamespace(id=1, name=f"{module}-acct", provider=module,
                                                          credentials=creds, regions=["r1"], labels={}))
        run = Mock(return_value=SimpleNamespace(returncode=returncode, stdout="{}", stderr=""))
        monkeypatch.setattr(f"agenticops.providers.{module}.subprocess.run", run)
        return provider.cli_tool(), run

    @pytest.mark.parametrize("module", ["azure", "gcp", "alicloud"])
    def test_write_is_recorded_with_provider_tool_name(self, db, monkeypatch, module):
        _c, tool_name, _creds, _ro, write_cmd, _pat = self.PROVIDERS[module]
        tool, run = self._tool(monkeypatch, module)
        assert tool(write_cmd) == "{}" and run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.account, row.exit_code, row.command) == \
               (tool_name, "unknown", "executed", f"{module}-acct", 0, write_cmd)

    @pytest.mark.parametrize("module", ["azure", "gcp", "alicloud"])
    def test_change_required_refused_without_subprocess(self, db, monkeypatch, module):
        from agenticops.services.policy_engine import PolicyEngine
        _c, tool_name, _creds, _ro, write_cmd, pattern = self.PROVIDERS[module]
        monkeypatch.setattr("agenticops.services.policy_engine._engine",
                            PolicyEngine({"rules": [], "change_required": [pattern]}))
        tool, run = self._tool(monkeypatch, module)
        out = tool(write_cmd)
        assert "/change" in out and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason) == (tool_name, "refused", "change_required")

    @pytest.mark.parametrize("module", ["azure", "gcp"])
    def test_readonly_not_recorded(self, db, monkeypatch, module):
        _c, _t, _creds, ro_cmd, *_ = self.PROVIDERS[module]
        tool, run = self._tool(monkeypatch, module)
        assert tool(ro_cmd) == "{}" and run.called
        assert _rows(db) == []

    def test_alicloud_camelcase_read_is_ledgered_as_unknown(self, db, monkeypatch):
        # generic_cli_tier knows list/show/get/describe(-…) only; aliyun's CamelCase Describe* is not on the
        # list, so it is unknown — recorded and gated (conservative direction), never silently skipped.
        tool, run = self._tool(monkeypatch, "alicloud")
        assert tool("aliyun ecs DescribeInstances") == "{}" and run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome) == ("provider_alicloud_cli", "unknown", "executed")
