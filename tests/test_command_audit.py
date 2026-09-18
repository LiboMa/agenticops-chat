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
        # SSM Run Command / Session Manager = arbitrary remote execution (fix wave, I-3)
        assert eng.change_required_match("aws ssm send-command --instance-ids i-1 --document-name AWS-RunShellScript "
                                         "--parameters commands=uptime") == "aws ssm send-command"
        assert eng.change_required_match("aws ssm start-session --target i-1") == "aws ssm start-session"
        assert eng.change_required_match("aws ssm describe-instance-information") is None

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

    @pytest.mark.parametrize("command", [
        "aws --region us-east-1 ec2 terminate-instances --instance-ids i-1",
        "aws --output json iam create-user --user-name x",
        "aws --region us-east-1 iam attach-user-policy --user-name x --policy-arn arn:aws:iam::aws:policy/AdministratorAccess",
        "aws --region us-east-1 iam create-access-key --user-name x",
        "aws --profile p organizations delete-organization",
        "aws ec2 terminate-instances --instance-ids i-1",
        "aws iam create-user --user-name x",
        "aws iam attach-user-policy --user-name x --policy-arn arn:aws:iam::aws:policy/AdministratorAccess",
        "aws iam create-access-key --user-name x",
        "aws organizations delete-organization",
    ])
    def test_destructive_is_blocked_even_with_global_options_before_the_service(self, db, command):
        """Fix round 2 (A): the destructive block entries are `<service> <verb>` without the `aws ` prefix, so a
        global option placed before the service (`aws --region … ec2 terminate-instances`) is still hard-blocked —
        confirmation or not — and never reaches execution."""
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
            out = run_aws_cli(command=command, require_confirmation=True)
        assert "blocked" in out.lower() and not ex.called
        (row,) = _rows(db)
        assert (row.tier, row.outcome) == ("blocked", "blocked")

    @pytest.mark.parametrize("command", ["aws ec2 describe-instances", "aws --region us-east-1 iam list-users"])
    def test_reads_with_global_options_are_not_blocked(self, db, command):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="{}") as ex:
            assert run_aws_cli(command=command, require_confirmation=True) == "{}"
        assert ex.called

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

    @pytest.mark.parametrize("command,pattern", [
        ("aws secretsmanager get-secret-value --secret-id x", "get-secret-value"),
        ("aws ssm get-parameter --name /prod/db --with-decryption", "--with-decryption"),
        ("aws ecr get-login-password --region us-east-1", "ecr get-login-password"),
        ("aws sts get-session-token", "sts get-session-token"),
        ("aws s3 rm --recursive s3://b/", "s3 rm --recursive"),   # the provider's own extra (substring, as before): not confirmation-gated here
    ])
    def test_provider_blocks_secret_revealing_reads_like_the_main_tool(self, db, monkeypatch, command, pattern):
        """Fix wave: the provider reuses aws_cli_tool.BLOCKED_PATTERNS (single source of truth), so the
        secret-revealing reads the main path blocks are blocked for sub-agent provider tools too."""
        tool, run, _ = self._tool(monkeypatch)
        out = tool(command)
        assert out == f"Error: Blocked dangerous pattern '{pattern}' in command." and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.reason) == ("provider_aws_cli", "blocked", "blocked", None)

    @pytest.mark.parametrize("command,pattern", [
        ("aws --region us-east-1 ec2 terminate-instances --instance-ids i-1", "ec2 terminate-instances"),
        ("aws --output json iam create-user --user-name x", "iam create-user"),
        ("aws --region us-east-1 iam attach-user-policy --user-name x --policy-arn arn:aws:iam::aws:policy/AdministratorAccess",
         "iam attach-"),
        ("aws --region us-east-1 iam create-access-key --user-name x", "iam create-access-key"),
        ("aws --profile p organizations delete-organization", "organizations delete-"),
        ("aws ec2 terminate-instances --instance-ids i-1", "ec2 terminate-instances"),
        ("aws iam create-user --user-name x", "iam create-user"),
        ("aws iam attach-user-policy --user-name x --policy-arn arn:aws:iam::aws:policy/AdministratorAccess", "iam attach-"),
        ("aws iam create-access-key --user-name x", "iam create-access-key"),
        ("aws organizations delete-organization", "organizations delete-"),
    ])
    def test_provider_blocks_destructive_commands_with_global_options_before_the_service(self, db, monkeypatch,
                                                                                         command, pattern):
        """Fix round 2 (A): 2.5.0 hard-blocked these on the provider path — which has NO confirmation gate — and the
        Group-7 switch to the shared list must not lose them when a global option precedes the service."""
        tool, run, _ = self._tool(monkeypatch)
        out = tool(command)
        assert out == f"Error: Blocked dangerous pattern '{pattern}' in command." and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.account) == ("provider_aws_cli", "blocked", "blocked", "dev")

    @pytest.mark.parametrize("command", ["aws ec2 describe-instances", "aws --region us-east-1 iam list-users"])
    def test_provider_reads_with_global_options_are_not_blocked(self, db, monkeypatch, command):
        tool, run, _ = self._tool(monkeypatch)
        assert tool(command) == "{}" and run.called

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
        with run_context(actor="a" * 300, trace_id="T" * 30, agent_name="g" * 60, on_behalf_of="b" * 300):
            record_command(tool="t" * 40, tier="write-tier-x", command="aws x", outcome="executed",
                           account="c" * 150, region="x" * 40, target="d" * 250, reason="r" * 60)
        (row,) = _rows(db)
        # actor keys are `user:<email>` (users.email is 255 wide) → actor / on_behalf_of are 255 (M-2)
        assert (len(row.actor), len(row.trace_id), len(row.agent_name), len(row.on_behalf_of)) == (255, 20, 50, 255)
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
    """Round 2: ordered token-subsequence match (prefix per token) replaces the round-1 substring test.

    Tokens = shlex split, sudo/env wrappers dropped, every `-`/`--` token dropped, option VALUES kept, lower-cased.
    A pattern hits when its whitespace-split tokens appear in order (not necessarily adjacent); a bare pattern word
    must equal the whole command token, a hyphenated one (`modify-`, `modify-security-group`) matches as a prefix
    (round 3). No raw-substring fallback. A kept token that still contains whitespace is a QUOTED PAYLOAD
    (`bash -c "…"`, `ssh host '…'`) and is re-split the same way, so its words face the gate too (round 4).
    Each token carries an `eligible_for_prefix` flag — False when the ORIGINAL token before it is a value-taking
    option (`-`-prefixed, not `-`/`--`, no `=`); only HYPHENATED pattern tokens consult it, so an option value such as
    `--function-name update-inventory` never hits `aws lambda update-` while bare verbs keep no adjacency rule.
    A known BOOLEAN flag (`--no-cli-pager`, `--debug`, `--dry-run`, `-q`, `--user`, `-A`, …: `_POLICY_BOOLEAN_FLAGS`)
    takes no value, so the token after it stays eligible and `aws ec2 --no-cli-pager modify-security-group-rules`
    is still gated.
    """

    @pytest.mark.parametrize("command", [
        "aws --profile p ec2 modify-security-group-rules --group-id sg-1",   # global option + value before the service
        "aws --query . ec2 modify-security-group-rules --group-id sg-1",     # option value that is not a known token
        "aws --cli-read-timeout 60 rds modify-db-instance",                  # numeric option value
        "aws --region=us-east-1 rds modify-db-instance --x",                 # --opt=value is a single token
        "kubectl --context prod delete pod x",                               # value-taking global option
        "kubectl --as admin delete pod x",
        "kubectl -v 6 delete pod x",
        "kubectl -n prod delete pod x",                                      # -n no longer ambiguous: value kept, flag dropped
        "systemctl  restart nginx",                                          # doubled whitespace
        "systemctl --user restart myapp",
        "sudo systemctl restart nginx",                                      # privilege wrapper (run_on_host)
        "sudo -n systemctl restart nginx",                                   # wrapper + boolean flag
        "sudo reboot",
    ])
    def test_high_risk_commands_match(self, command):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) is not None

    @pytest.mark.parametrize("command", [
        "aws ec2 describe-instances --region x",
        "kubectl scale deployment/x --replicas=2",
        "kubectl scale deployment/shutdown-handler --replicas=2",                # pattern word inside a positional, not a token prefix
        "aws ec2 create-tags --resources i-1 --tags Key=x,Value=reboot-test",   # pattern word inside an option value
        "kubectl label pod delete-me tier=web",                                 # round 3: bare `delete` needs the whole token
        "systemctl restart-all-the-things",                                     # round 3: bare `restart` needs the whole token
    ])
    def test_non_matching_commands_stay_unmatched(self, command):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) is None

    def test_normalize_for_policy_returns_tokens_with_prefix_eligibility(self):
        """(token, eligible_for_prefix): a token right after a value-taking option is NOT eligible; `--opt=value`
        is self-contained so the next token stays eligible; sudo/env and `-` tokens are dropped."""
        from agenticops.services.policy_engine import _normalize_for_policy
        assert _normalize_for_policy("kubectl -n prod delete pod x") == \
               [("kubectl", True), ("prod", False), ("delete", True), ("pod", True), ("x", True)]
        assert _normalize_for_policy("sudo -u postgres systemctl restart pg") == \
               [("postgres", False), ("systemctl", True), ("restart", True), ("pg", True)]
        assert _normalize_for_policy("env FOO=1 aws --profile=p EC2 modify-x --group-id sg-1") == \
               [("foo=1", True), ("aws", True), ("ec2", True), ("modify-x", True), ("sg-1", False)]
        assert _normalize_for_policy("systemctl restart 'nginx") == \
               [("systemctl", True), ("restart", True), ("'nginx", True)]                 # unbalanced quote → str.split
        assert _normalize_for_policy("kubectl exec pod -- rm-rf-ish arg") == \
               [("kubectl", True), ("exec", True), ("pod", True), ("rm-rf-ish", True), ("arg", True)]  # `--` is a marker, not an option
        assert _normalize_for_policy("") == []

    def test_pattern_tokens_are_ordered_prefixes(self):
        from agenticops.services.policy_engine import PolicyEngine
        eng = PolicyEngine({"rules": [], "change_required": ["aws rds modify-", "kubectl delete"]})
        assert eng.change_required_match("aws rds modify-db-instance") == "aws rds modify-"
        assert eng.change_required_match("aws --profile p rds modify-db-instance") == "aws rds modify-"   # not adjacent (`p` between)
        # Round-4 addendum: an option directly BEFORE a hyphenated token makes it an option VALUE (`--x` might take
        # one), so the round-2 "not adjacent" shape is now a documented pass — see test_option_values_are_not_eligible…
        assert eng.change_required_match("aws rds --x modify-db-instance") is None
        assert eng.change_required_match("rds aws modify-db-instance") is None                     # order matters
        assert eng.change_required_match("aws rds modif") is None                                  # prefix runs pattern→command only
        assert eng.change_required_match("aws rds") is None                                        # every pattern token must be consumed
        assert eng.change_required_match("kubectl delete pod x") == "kubectl delete"

    def test_bare_words_match_whole_tokens_hyphenated_match_prefixes(self):
        """Round 3: `kubectl label pod delete-me` is a legitimate L1 write and must not be refused as `kubectl delete`."""
        from agenticops.services.policy_engine import get_policy_engine
        eng = get_policy_engine(reload=True)
        assert eng.change_required_match("kubectl label pod delete-me") is None
        assert eng.change_required_match("kubectl delete pod x") == "kubectl delete"
        assert eng.change_required_match("aws ec2 modify-security-group-rules --group-id sg-1") == "aws ec2 modify-security-group"
        assert eng.change_required_match("aws rds modify-db-instance --x") == "aws rds modify-"
        assert eng.change_required_match("sudo reboot") == "reboot"
        assert eng.change_required_match("systemctl restart-all-the-things") is None
        # Policy ruling (round 3): EC2 reboot/stop are service-affecting and have their own hyphenated entries;
        # the bare `reboot` word no longer prefix-hits, and `start-` is deliberately NOT gated.
        assert eng.change_required_match("aws ec2 reboot-instances --instance-ids i-1") == "aws ec2 reboot-"
        assert eng.change_required_match("aws ec2 stop-instances --instance-ids i-1") == "aws ec2 stop-"
        assert eng.change_required_match("aws ec2 start-instances --instance-ids i-1") is None

    @pytest.mark.parametrize("command,pattern", [
        ('bash -c "systemctl restart nginx"', "systemctl restart"),
        ('bash -lc "kubectl delete pod x"', "kubectl delete"),
        ('sh -c "systemctl restart nginx"', "systemctl restart"),
        ("bash -c 'systemctl stop nginx'", "systemctl stop"),
        ('ssh host "sudo systemctl restart nginx"', "systemctl restart"),      # inner sudo dropped like an outer one
        ('su -c "systemctl restart nginx"', "systemctl restart"),
        ("nohup systemctl restart nginx &", "systemctl restart"),
        ("timeout 30 systemctl restart nginx", "systemctl restart"),
        ('bash -c "cd /srv && systemctl restart nginx"', "systemctl restart"),  # payload with shell operators
        ("bash -c \"sh -c 'systemctl restart nginx'\"", "systemctl restart"),   # two shells deep
    ])
    def test_quoted_shell_payloads_are_inspected(self, command, pattern):
        """Round 4: a quoted payload survived shlex as ONE token and nothing looked inside it — `bash -c
        "systemctl restart nginx"` (tier unknown) walked through the run_on_host gate. Re-splitting closes it."""
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) == pattern

    @pytest.mark.parametrize("command", [
        'bash -c "systemctl status nginx"',                                          # read inside a wrapper stays clean
        'aws ec2 create-tags --resources i-1 --tags Key=x,Value="reboot test"',     # re-splits to `key=x,value=reboot` + `test`:
        'aws ec2 create-tags --resources i-1 --tags "Key=x,Value=reboot test"',     #   the value stays glued to its key, so the
        "aws ec2 create-tags --resources i-1 --tags Key=x,Value=reboot-test",       #   bare `reboot` still has no exact token
    ])
    def test_quoted_payload_negatives_stay_unmatched(self, command):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) is None

    @pytest.mark.parametrize("command,pattern", [
        ('echo "kubectl delete pod x"', "kubectl delete"),
        ('aws ec2 create-snapshot --volume-id vol-1 --description "reboot test"', "reboot"),
    ])
    def test_free_text_payload_matches_are_deliberate(self, command, pattern):
        """Pinned ON PURPOSE (ruling: the gate prefers a false refusal over a false pass). The normaliser cannot
        tell a quoted script from quoted prose, so a pattern word inside free text (an echo, a --description) is
        refused too. Tune with a more specific yaml entry, not by weakening the payload inspection."""
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) == pattern

    def test_normalize_for_policy_resplits_quoted_payloads(self):
        """A re-split payload is a command in its own right: eligibility is judged INSIDE it (its first word has no
        predecessor), so `bash -c "aws ec2 modify-…"` keeps the hyphenated gate — see 12.7 for the deviation."""
        from agenticops.services.policy_engine import _normalize_for_policy
        assert _normalize_for_policy('bash -c "systemctl restart nginx"') == \
               [("bash", True), ("systemctl", True), ("restart", True), ("nginx", True)]
        assert _normalize_for_policy('ssh host "sudo systemctl restart nginx"') == \
               [("ssh", True), ("host", True), ("systemctl", True), ("restart", True), ("nginx", True)]
        assert _normalize_for_policy('bash -c "kubectl -n prod delete pod x"') == \
               [("bash", True), ("kubectl", True), ("prod", False), ("delete", True), ("pod", True), ("x", True)]
        assert _normalize_for_policy('bash -c "echo \'oops"') == [("bash", True), ("echo", True), ("'oops", True)]  # inner unbalanced quote → str.split
        assert _normalize_for_policy('bash -c " "') == [("bash", True)]                                             # whitespace-only payload adds nothing

    @pytest.mark.parametrize("command,pattern", [
        # Round-4 addendum (lead ruling): a verb-shaped RESOURCE NAME in an option value is not an operation.
        ("aws lambda invoke --function-name update-inventory", None),
        ("aws rds create-db-instance --db-instance-identifier modify-test", None),
        ("aws ec2 run-instances --key-name stop-key", None),
        # …while the operation token itself (preceded by the service, a positional or a self-contained --opt=value) still hits.
        ("aws --profile p rds modify-db-instance --x", "aws rds modify-"),
        ("aws --region=us-east-1 ec2 modify-security-group-rules", "aws ec2 modify-security-group"),
        ("aws ec2 --region=us-east-1 modify-security-group-rules --group-id sg-1", "aws ec2 modify-security-group"),
        ("aws ec2 stop-instances --instance-ids i-1", "aws ec2 stop-"),
        # Bare pattern words keep NO adjacency rule (the value after `--user` / `--as` is irrelevant to them).
        ("systemctl --user restart myapp", "systemctl restart"),
        ("kubectl --as admin delete pod x", "kubectl delete"),
        # Deviation from the literal addendum: a `-c` payload is a command in its own right, not prose — taking its
        # tokens as ineligible would re-open the round-4 hole for every hyphenated (AWS-style) pattern.
        ('bash -c "aws ec2 modify-security-group-rules --group-id sg-1"', "aws ec2 modify-security-group"),
        # A known BOOLEAN flag directly before the operation does not claim it as a value (allowlist ruling): the
        # operation stays eligible, so these AWS global-flag placements are refusals, not passes.
        ("aws ec2 --no-cli-pager modify-security-group-rules --group-id sg-1", "aws ec2 modify-security-group"),
        ("aws --debug ec2 modify-security-group-rules", "aws ec2 modify-security-group"),
        ("aws ec2 --no-paginate --no-cli-pager stop-instances --instance-ids i-1", "aws ec2 stop-"),
        # …while an UNKNOWN flag right before the operation still reads as value-taking (bound, pinned visible).
        ("aws ec2 --some-new-flag modify-security-group-rules --group-id sg-1", None),
    ])
    def test_option_values_are_not_eligible_for_hyphenated_patterns(self, command, pattern):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) == pattern

    @pytest.mark.parametrize("flag", [
        "--debug", "--no-cli-pager", "--no-paginate", "--no-verify-ssl", "--no-sign-request", "--no-cli-auto-prompt",
        "--cli-auto-prompt", "--dry-run", "--quiet", "-q", "--yes", "-y", "--force", "-f", "--user", "--now", "--all", "-A",
    ])
    def test_boolean_flags_do_not_claim_the_next_token(self, flag):
        """Every allowlisted boolean flag leaves its successor eligible for hyphenated patterns; the check is exact
        and case-sensitive (`-a` is not `-A`), and a genuinely value-taking option still shields its value."""
        from agenticops.services.policy_engine import _is_value_taking_option, _normalize_for_policy
        assert _is_value_taking_option(flag) is False
        assert _normalize_for_policy(f"aws ec2 {flag} modify-security-group-rules --group-id sg-1") == \
               [("aws", True), ("ec2", True), ("modify-security-group-rules", True), ("sg-1", False)]
        for value_taking in ("-n", "--profile", "--function-name", "-a", "--User", flag + "x"):
            assert _is_value_taking_option(value_taking) is True, value_taking

    def test_normalize_for_policy_recursion_is_bounded(self):
        """Depth ≤ 3 recursive re-splits, then a flat str.split — the bound caps the shlex passes (cost), never
        the matching: four nested shells resolve by re-splitting, five (and ten) by the flat split plus the
        edge-punctuation strip at comparison time (fix wave: leading `'"` layers are not part of a word) — and
        nothing ever raises."""
        import shlex
        from agenticops.services.policy_engine import _normalize_for_policy, get_policy_engine
        eng = get_policy_engine(reload=True)
        four = "systemctl restart nginx"
        for _ in range(4):
            four = f"bash -c {shlex.quote(four)}"
        five = f"bash -c {shlex.quote(four)}"
        ten = five
        for _ in range(5):
            ten = f"bash -c {shlex.quote(ten)}"
        assert eng.change_required_match(four) == "systemctl restart"
        assert eng.change_required_match(five) == "systemctl restart"
        assert eng.change_required_match(ten) == "systemctl restart"
        assert isinstance(_normalize_for_policy(ten), list)

    @pytest.mark.parametrize("command", ["", "   ", "--", "-", "sudo", "sudo env", None, "systemctl restart 'nginx"])
    def test_odd_inputs_never_raise(self, command):
        from agenticops.services.policy_engine import _normalize_for_policy, get_policy_engine
        tokens = _normalize_for_policy(command)
        assert isinstance(tokens, list)
        match = get_policy_engine(reload=True).change_required_match(command)
        assert match == ("systemctl restart" if command == "systemctl restart 'nginx" else None)


class TestChangeRequiredFixWave:
    """Final fix wave (I-3 + M-1): (1) a token in COMMAND POSITION — the first word after the wrappers
    `sudo [-u x]` / `env [K=V…]` / `nohup` / `time` / `nice`, and the first word of every re-split payload — is
    reduced to its basename, so `/bin/systemctl` is `systemctl`; a path anywhere else is left alone. (2) Any
    post-shlex token that still contains whitespace is a payload: `name="cmd …"` re-splits its VALUE part, a
    JSON body's structure (`{}[]":`) separates words, and tokens from an option's value keep the option-value
    flag (a `-c` shell payload is still a command in its own right — pinned above). (3) Edge punctuation
    `[{("'` / `]})"',` is stripped before comparison. (4) `--cli-auto-prompt` is a boolean AWS global. (5) Fix round 2:
    sudo's own boolean switches (`-n`, `-E`, …) take no value, so `sudo -n /usr/bin/systemctl` keeps the command position."""

    @pytest.mark.parametrize("command,pattern", [
        ("/bin/systemctl restart nginx", "systemctl restart"),
        ("/usr/bin/systemctl restart nginx", "systemctl restart"),
        ("sudo /usr/bin/systemctl restart nginx", "systemctl restart"),
        ("sudo -u root /usr/bin/systemctl restart nginx", "systemctl restart"),
        ("sudo -u deploy /usr/bin/systemctl restart nginx", "systemctl restart"),
        ("sudo -n /usr/bin/systemctl restart nginx", "systemctl restart"),           # fix round 2: sudo's own boolean switch
        ("sudo -E /bin/systemctl restart nginx", "systemctl restart"),
        ("nice -n 10 /usr/bin/systemctl restart nginx", "systemctl restart"),
        ("env FOO=1 /usr/bin/systemctl restart nginx", "systemctl restart"),
        ('bash -c "/bin/systemctl restart nginx"', "systemctl restart"),
        ("ssh host 'sudo /usr/sbin/reboot'", "reboot"),
        ("/sbin/reboot", "reboot"),
        ('aws ssm send-command --instance-ids i-1 --document-name AWS-RunShellScript '
         '--parameters \'{"commands":["systemctl restart nginx"]}\'', "aws ssm send-command"),
        ('aws ssm send-command --document-name AWS-RunShellScript --parameters commands="systemctl restart nginx" '
         '--instance-ids i-1', "aws ssm send-command"),
        ("aws ssm start-session --target i-1", "aws ssm start-session"),
        ("aws ec2 --cli-auto-prompt modify-security-group-rules --group-id sg-1", "aws ec2 modify-security-group"),
        ('echo "(systemctl restart nginx)"', "systemctl restart"),                      # edge punctuation stripped
    ])
    def test_refused(self, command, pattern):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) == pattern

    @pytest.mark.parametrize("command", [
        "kubectl apply -f /tmp/delete-me.yaml",                                  # a path OUTSIDE command position
        "aws s3 cp /tmp/reboot-notes.txt s3://b/",
        "aws ec2 create-tags --resources i-1 --tags Key=Name,Value=web-restart",
        "aws lambda invoke --function-name update-inventory",
        "aws ssm describe-instance-information",
        "aws ssm get-command-invocation --command-id c-1 --instance-id i-1",
        "kubectl cp /tmp/reboot pod:/tmp/reboot",
    ])
    def test_not_refused(self, command):
        from agenticops.services.policy_engine import get_policy_engine
        assert get_policy_engine(reload=True).change_required_match(command) is None

    def test_basename_applies_only_in_command_position(self):
        from agenticops.services.policy_engine import _normalize_for_policy
        assert _normalize_for_policy("/bin/systemctl restart nginx") == \
               [("systemctl", True), ("restart", True), ("nginx", True)]
        assert _normalize_for_policy("sudo -u postgres /usr/bin/systemctl restart pg") == \
               [("postgres", False), ("systemctl", True), ("restart", True), ("pg", True)]     # `-u x` is not the command
        assert _normalize_for_policy("env FOO=1 /usr/local/bin/aws ec2 modify-x") == \
               [("foo=1", True), ("aws", True), ("ec2", True), ("modify-x", True)]             # K=V is not the command
        assert _normalize_for_policy("kubectl apply -f /tmp/delete-me.yaml") == \
               [("kubectl", True), ("apply", True), ("/tmp/delete-me.yaml", True)]             # positional path untouched
        assert _normalize_for_policy('bash -c "/bin/systemctl restart nginx"') == \
               [("bash", True), ("systemctl", True), ("restart", True), ("nginx", True)]       # payload's own command word
        assert _normalize_for_policy("ssh host 'sudo /usr/sbin/reboot'") == \
               [("ssh", True), ("host", True), ("reboot", True)]

    def test_named_and_json_payloads_resplit_and_keep_the_option_value_flag(self):
        """`name="cmd …"` re-splits its value; a JSON body's structure separates its words; both are the VALUE of
        `--parameters`, so their tokens are ineligible for hyphenated patterns (bare words still match)."""
        from agenticops.services.policy_engine import _normalize_for_policy
        assert _normalize_for_policy('aws ssm send-command --parameters commands="systemctl restart nginx"') == \
               [("aws", True), ("ssm", True), ("send-command", True), ("systemctl", False), ("restart", False), ("nginx", False)]
        assert _normalize_for_policy('aws ssm send-command --parameters \'{"commands":["systemctl restart nginx"]}\'') == \
               [("aws", True), ("ssm", True), ("send-command", True),
                ("commands", False), ("systemctl", False), ("restart", False), ("nginx", False)]
        # a positional name=payload is a command in its own right (no option-value flag to keep)
        assert _normalize_for_policy('run commands="systemctl restart nginx"') == \
               [("run", True), ("systemctl", True), ("restart", True), ("nginx", True)]
        # a `-c` payload stays a command in its own right (round-4 deviation, unchanged)
        assert _normalize_for_policy('bash -c "aws ec2 modify-security-group-rules --group-id sg-1"') == \
               [("bash", True), ("aws", True), ("ec2", True), ("modify-security-group-rules", True), ("sg-1", False)]
        # …so a hyphenated pattern inside a NON-shell option value never hits, even re-split
        from agenticops.services.policy_engine import PolicyEngine
        eng = PolicyEngine({"rules": [], "change_required": ["aws ec2 modify-security-group"]})
        assert eng.change_required_match('aws ssm send-command --parameters commands="aws ec2 modify-security-group-rules"') is None
        assert eng.change_required_match('bash -c "aws ec2 modify-security-group-rules"') == "aws ec2 modify-security-group"

    def test_edge_punctuation_is_stripped_only_for_comparison(self):
        from agenticops.services.policy_engine import _normalize_for_policy, _tokens_match_in_order
        assert _tokens_match_in_order(["reboot"], [("(reboot)", True)]) is True
        assert _tokens_match_in_order(["reboot"], [("'reboot',", True)]) is True
        assert _tokens_match_in_order(["kubectl", "delete"], [("kubectl", True), ("[delete]", True)]) is True
        assert _tokens_match_in_order(["reboot"], [("reboot-test", True)]) is False
        assert _normalize_for_policy("systemctl restart 'nginx") == \
               [("systemctl", True), ("restart", True), ("'nginx", True)]                       # normalisation output unchanged

    def test_cli_auto_prompt_is_a_boolean_flag(self):
        from agenticops.services.policy_engine import _POLICY_BOOLEAN_FLAGS, _is_value_taking_option, _normalize_for_policy
        assert "--cli-auto-prompt" in _POLICY_BOOLEAN_FLAGS and _is_value_taking_option("--cli-auto-prompt") is False
        assert _normalize_for_policy("aws ec2 --cli-auto-prompt modify-security-group-rules --group-id sg-1") == \
               [("aws", True), ("ec2", True), ("modify-security-group-rules", True), ("sg-1", False)]

    def test_sudo_boolean_switches_leave_the_command_position_in_place(self):
        """Fix round 2 (B): sudo's own boolean switches (`-n -E -i -H -b -k -K -s -S -v`) take no value, so the path
        after them IS the command position and is basenamed. Per wrapper on purpose: the generic `-n` stays
        value-taking (`nice -n 10` shields `10`), `sudo -u deploy` still shields `deploy`, and the table applies only
        in sudo's own option region — a `-n` after the command word is generic again."""
        from agenticops.services.policy_engine import (
            _WRAPPER_BOOLEAN_FLAGS, _is_value_taking_option, _normalize_for_policy,
        )
        assert _WRAPPER_BOOLEAN_FLAGS["sudo"] == frozenset({"-n", "-E", "-i", "-H", "-b", "-k", "-K", "-s", "-S", "-v"})
        assert set(_WRAPPER_BOOLEAN_FLAGS) == {"sudo"}
        assert _is_value_taking_option("-n") is True and _is_value_taking_option("-E") is True   # generic rule unchanged
        for flag in sorted(_WRAPPER_BOOLEAN_FLAGS["sudo"]):
            assert _normalize_for_policy(f"sudo {flag} /usr/bin/systemctl restart nginx") == \
                   [("systemctl", True), ("restart", True), ("nginx", True)], flag
        assert _normalize_for_policy("sudo -u deploy -n /usr/bin/systemctl restart nginx") == \
               [("deploy", False), ("systemctl", True), ("restart", True), ("nginx", True)]     # `-u x` then `-n`
        assert _normalize_for_policy("sudo -u deploy /usr/bin/systemctl restart nginx") == \
               [("deploy", False), ("systemctl", True), ("restart", True), ("nginx", True)]     # value-taking `-u` still works
        assert _normalize_for_policy("nice -n 10 /usr/bin/systemctl restart nginx") == \
               [("10", False), ("systemctl", True), ("restart", True), ("nginx", True)]         # nice's `-n` takes a value
        assert _normalize_for_policy("sudo /usr/bin/foo -n /usr/bin/systemctl restart nginx") == \
               [("foo", True), ("/usr/bin/systemctl", False), ("restart", True), ("nginx", True)]  # past the command word: generic

    @pytest.mark.parametrize("command", ["/", "//", "sudo /", "bash -c '/'", "a/ b", '{"x": [1, 2]}', "name=", "FOO= bar"])
    def test_odd_paths_and_payloads_never_raise(self, command):
        from agenticops.services.policy_engine import _normalize_for_policy, get_policy_engine
        assert isinstance(_normalize_for_policy(command), list)
        assert get_policy_engine(reload=True).change_required_match(command) is None


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
        # Round 2: first verb wins — a read verb AFTER a mutating verb is a positional (resource name), not a verb.
        ("gcloud compute instances delete list --zone z", "unknown"),
        ("gcloud compute instances delete get-started-vm --zone z", "unknown"),
        ("gcloud container clusters delete describe-me", "unknown"),
        ("gcloud compute instances list --zone z", "readonly"),
        ("az group delete -n x", "unknown"),
        ("az vm run-command invoke --command-id RunShellScript", "unknown"),    # run- prefix
        ("gcloud iam service-accounts set-iam-policy sa pol.json", "unknown"),  # set- prefix
        # Leading global options: `--opt value` drops both tokens, `--opt=value` drops one; a value is never a verb.
        ("gcloud --project p compute instances list", "readonly"),
        ("az --output=json vm list", "readonly"),
        ("gcloud --project get-started compute instances delete x", "unknown"),
        ("gcloud compute ssh vm-1 --zone z", "unknown"),                        # no verb at all → unknown
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
