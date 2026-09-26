"""G10 — a change review / unapproved-change run is read-only IN CODE, not just in the prompt.

While the Run Context names a change request and no approved/executing plan is in context, every
write-tier command tool refuses before it can mutate anything (`change_not_approved`); a readonly
command still runs; an approved plan in context lifts the guard. Mirrors the fixtures of
tests/test_command_audit.py (the ledger is ON here; conftest keeps it OFF by default).
"""
from unittest.mock import Mock, patch

import pytest

from agenticops.models import Base, CommandAudit, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import run_context

REFUSAL = "no approved plan yet"  # a substring of change_context_refusal's text


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cmd.db"
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    monkeypatch.setattr(settings, "change_management_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _rows(db):
    db.expire_all()
    return db.query(CommandAudit).order_by(CommandAudit.id).all()


def _approved_plan(db) -> int:
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s", status="approved")
    db.add(plan); db.commit()
    return plan.id


class TestChangeContextRefusal:
    def test_a_aws_write_refused_under_a_change_review(self, db):
        # write, but NOT a change_required pattern — on BASE it would EXECUTE; the change context must refuse it.
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with run_context(change_request_id=7), \
             patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
            out = run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b",
                              require_confirmation=True)
        assert REFUSAL in out and not ex.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason, row.change_request_id) == \
               ("run_aws_cli", "refused", "change_not_approved", 7)

    def test_b_aws_readonly_still_runs(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli_readonly
        with run_context(change_request_id=7), \
             patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="{}") as ex:
            assert run_aws_cli_readonly(command="aws ec2 describe-instances") == "{}"
        assert ex.called and _rows(db) == []

    def test_c_aws_write_allowed_inside_an_approved_plan(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        pid = _approved_plan(db)
        with run_context(change_request_id=7, fix_plan_id=pid), \
             patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
            out = run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b",
                              require_confirmation=True)
        assert out == "ok" and ex.called
        (row,) = _rows(db)
        assert (row.outcome, row.fix_plan_id) == ("executed", pid)

    def test_d_run_on_host_write_refused(self, db):
        # `kill -9` is write but not change_required — on BASE it would run via the auto ladder.
        from agenticops.skills.execution import run_on_host
        with run_context(change_request_id=7), \
             patch("agenticops.skills.execution._run_auto_ladder", return_value="ok") as ladder:
            out = run_on_host(host_id="i-1", command="kill -9 1234", require_confirmation=True)
        assert REFUSAL in out and not ladder.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason, row.target) == \
               ("run_on_host", "refused", "change_not_approved", "i-1")

    def test_d_run_on_host_readonly_runs(self, db):
        from agenticops.skills.execution import run_on_host
        with run_context(change_request_id=7), \
             patch("agenticops.skills.execution._run_auto_ladder", return_value="ok") as ladder:
            assert run_on_host(host_id="i-1", command="df -h") == "ok"
        assert ladder.called and _rows(db) == []

    def test_e_run_kubectl_write_refused(self, db):
        # `scale` is write but not change_required — on BASE it would reach _execute_kubectl.
        from agenticops.skills.execution import run_kubectl
        with run_context(change_request_id=7), \
             patch("agenticops.skills.execution._execute_kubectl", return_value="ok") as ex:
            out = run_kubectl(cluster_name="c1", command="scale deployment/x --replicas=2",
                              namespace="prod", require_confirmation=True)
        assert REFUSAL in out and not ex.called
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.reason, row.target, row.command) == \
               ("run_kubectl", "refused", "change_not_approved", "c1",
                "kubectl -n prod scale deployment/x --replicas=2")

    def test_e_run_kubectl_readonly_runs(self, db):
        from agenticops.skills.execution import run_kubectl
        with run_context(change_request_id=7), \
             patch("agenticops.skills.execution._execute_kubectl", return_value="NAME") as ex:
            assert run_kubectl(cluster_name="c1", command="get pods") == "NAME"
        assert ex.called and _rows(db) == []

    def test_f_guarded_run_refused_under_a_change_context(self, db):
        from agenticops.services.command_audit import guarded_run
        run = Mock(return_value="ok")
        with run_context(change_request_id=7):
            out = guarded_run(tool="provider_aws_cli", tier="write",
                              command="aws ec2 delete-vpc --vpc-id vpc-1", run=run,
                              outcome_of=lambda t: ("executed", 0), account="dev", target="vpc-1")
        assert REFUSAL in out and not run.called
        (row,) = _rows(db)
        assert (row.tool, row.tier, row.outcome, row.reason, row.account, row.target) == \
               ("provider_aws_cli", "write", "refused", "change_not_approved", "dev", "vpc-1")

    def test_no_change_context_is_unaffected(self, db):
        # sanity: with no change_request_id the guard is a no-op — a confirmed write still executes.
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
            assert run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b",
                               require_confirmation=True) == "ok"
        assert ex.called
        (row,) = _rows(db)
        assert row.outcome == "executed"
