"""E2E tests for the Auto-Fix Pipeline: RCA → SRE → Approve → Execute → Resolve.

Tests exercise the full pipeline wiring with mocked agent calls. The real DB
state transitions, pipeline_service triggers, and metadata_tools hooks are
all tested against an actual SQLite database.

Run:
    pytest tests/test_auto_fix_pipeline.py -v
"""

import json
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import (
    Base,
    FixExecution,
    FixPlan,
    HealthIssue,
    RCAResult,
    get_engine,
    get_session,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary SQLite database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test_pipeline.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def enable_pipeline():
    """Enable all pipeline flags for testing."""
    from agenticops.config import settings

    orig_auto_fix = settings.auto_fix_enabled
    orig_auto_approve = settings.executor_auto_approve_l0_l1
    orig_executor = settings.executor_enabled
    orig_auto_rca = settings.auto_rca_enabled
    orig_auto_resolve = settings.executor_auto_resolve

    settings.auto_fix_enabled = True
    settings.executor_auto_approve_l0_l1 = True
    settings.executor_enabled = True
    settings.auto_rca_enabled = False  # Disable auto-RCA to control flow manually
    settings.executor_auto_resolve = True

    yield

    settings.auto_fix_enabled = orig_auto_fix
    settings.executor_auto_approve_l0_l1 = orig_auto_approve
    settings.executor_enabled = orig_executor
    settings.auto_rca_enabled = orig_auto_rca
    settings.executor_auto_resolve = orig_auto_resolve


@pytest.fixture
def disable_pipeline():
    """Disable the auto-fix pipeline for gate tests."""
    from agenticops.config import settings

    orig = settings.auto_fix_enabled
    settings.auto_fix_enabled = False
    yield
    settings.auto_fix_enabled = orig


def _create_test_issue(session) -> int:
    """Create a test HealthIssue in 'open' status."""
    issue = HealthIssue(
        resource_id="i-0e2e4a6c8f0123456",
        severity="high",
        source="cloudwatch_alarm",
        title="EC2 CPU > 95% for 10 minutes",
        description="Instance i-0e2e4a6c8f0123456 CPU utilization spiked.",
        alarm_name="prod-web-cpu-alarm",
        status="open",
    )
    session.add(issue)
    session.commit()
    return issue.id


def _create_rca_result(session, issue_id: int) -> int:
    """Create an RCA result and set issue to 'root_cause_identified'."""
    rca = RCAResult(
        health_issue_id=issue_id,
        root_cause="Runaway process consuming 100% CPU due to infinite loop in v2.3 deployment",
        confidence=0.92,
        contributing_factors=["Bad deployment v2.3", "No CPU cgroup limits"],
        recommendations=["Kill runaway process", "Rollback deployment", "Add cgroup limits"],
        fix_plan={
            "steps": [
                {"action": "host_command", "command": "kill -9 $(pgrep -f worker_v2.3)"},
                {"action": "aws_cli", "command": "aws deploy create-deployment --application-name prod-app --deployment-group-name prod-fleet --revision '{\"revisionType\":\"S3\"}'"},
            ]
        },
        fix_risk_level="medium",
        model_id="test-model",
    )
    session.add(rca)
    issue = session.query(HealthIssue).filter_by(id=issue_id).first()
    issue.status = "root_cause_identified"
    session.commit()
    return rca.id


def _create_fix_plan(session, issue_id: int, rca_id: int, risk_level: str = "L1") -> int:
    """Create a FixPlan in 'draft' status and set issue to 'fix_planned'."""
    plan = FixPlan(
        health_issue_id=issue_id,
        rca_result_id=rca_id,
        risk_level=risk_level,
        title="Kill runaway process and rollback deployment",
        summary="SSH to instance, kill the stuck worker process, rollback to v2.2",
        steps=[
            {
                "step_index": 1,
                "action": "host_command",
                "command": "kill -9 $(pgrep -f worker_v2.3)",
                "description": "Kill the runaway process",
            },
            {
                "step_index": 2,
                "action": "host_command",
                "command": "systemctl restart app-worker",
                "description": "Restart the worker service",
            },
        ],
        rollback_plan={
            "steps": [
                {"action": "host_command", "command": "systemctl restart app-worker"},
            ]
        },
        pre_checks=[
            {"check": "verify CPU > 90%", "command": "top -bn1 | head -5"},
        ],
        post_checks=[
            {"check": "verify CPU < 50%", "command": "top -bn1 | head -5"},
        ],
        status="draft",
    )
    session.add(plan)
    issue = session.query(HealthIssue).filter_by(id=issue_id).first()
    issue.status = "fix_planned"
    session.commit()
    return plan.id


# ── Test Classes ──────────────────────────────────────────────────────


class TestPipelineServiceTriggers:
    """Test that pipeline_service trigger functions work correctly."""

    def test_trigger_auto_sre_spawns_thread(self, db_session, enable_pipeline):
        """trigger_auto_sre should spawn a daemon thread that calls sre_agent."""
        issue_id = _create_test_issue(db_session)
        _create_rca_result(db_session, issue_id)

        with patch("agenticops.services.pipeline_service._run_auto_sre") as mock_run:
            from agenticops.services.pipeline_service import trigger_auto_sre

            trigger_auto_sre(issue_id)
            time.sleep(0.2)  # Let daemon thread start
            mock_run.assert_called_once_with(issue_id)

    def test_trigger_auto_sre_disabled(self, db_session, disable_pipeline):
        """trigger_auto_sre should be a no-op when pipeline is disabled."""
        with patch("agenticops.services.pipeline_service._run_auto_sre") as mock_run:
            from agenticops.services.pipeline_service import trigger_auto_sre

            trigger_auto_sre(1)
            time.sleep(0.1)
            mock_run.assert_not_called()

    def test_trigger_auto_approve_l0(self, db_session, enable_pipeline):
        """L0 plans should be auto-approved."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L0")

        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)

            # Verify plan was approved
            db_session.expire_all()
            plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
            assert plan.status == "approved"
            assert plan.approved_by == "agent:auto-pipeline"
            assert plan.approved_at is not None

            # Verify issue status advanced
            issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
            assert issue.status == "fix_approved"

            # Verify execution was triggered
            mock_exec.assert_called_once_with(plan_id)

    def test_trigger_auto_approve_l1(self, db_session, enable_pipeline):
        """L1 plans should also be auto-approved."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L1")

        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)

            db_session.expire_all()
            plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
            assert plan.status == "approved"
            mock_exec.assert_called_once_with(plan_id)

    def test_trigger_auto_approve_l2_skipped(self, db_session, enable_pipeline):
        """L2 plans should NOT be auto-approved (require human approval)."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L2")

        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)

            db_session.expire_all()
            plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
            assert plan.status == "draft"  # Unchanged
            mock_exec.assert_not_called()

    def test_trigger_auto_approve_l3_skipped(self, db_session, enable_pipeline):
        """L3 plans should NOT be auto-approved."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L3")

        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)

            db_session.expire_all()
            plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
            assert plan.status == "draft"
            mock_exec.assert_not_called()

    def test_trigger_auto_execute_spawns_thread(self, db_session, enable_pipeline):
        """trigger_auto_execute should spawn a daemon thread."""
        with patch("agenticops.services.pipeline_service._run_auto_execute") as mock_run:
            from agenticops.services.pipeline_service import trigger_auto_execute

            trigger_auto_execute(42)
            time.sleep(0.2)
            mock_run.assert_called_once_with(42)

    def test_trigger_auto_execute_disabled(self, db_session):
        """trigger_auto_execute should be a no-op when executor is disabled."""
        from agenticops.config import settings

        orig = settings.executor_enabled
        settings.executor_enabled = False
        try:
            with patch("agenticops.services.pipeline_service._run_auto_execute") as mock_run:
                from agenticops.services.pipeline_service import trigger_auto_execute

                trigger_auto_execute(42)
                time.sleep(0.1)
                mock_run.assert_not_called()
        finally:
            settings.executor_enabled = orig


class TestMetadataToolHooks:
    """Test that metadata tools trigger the pipeline correctly."""

    def test_save_rca_result_triggers_auto_sre(self, db_session, enable_pipeline):
        """save_rca_result() should call trigger_auto_sre."""
        issue_id = _create_test_issue(db_session)
        # Set to investigating first (valid transition from open)
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        issue.status = "investigating"
        db_session.commit()

        with patch("agenticops.services.pipeline_service.trigger_auto_sre") as mock_trigger:
            from agenticops.tools.metadata_tools import save_rca_result

            result = save_rca_result(
                health_issue_id=issue_id,
                root_cause="Memory leak in worker process",
                confidence=0.85,
                contributing_factors='["No memory limits", "Long-running process"]',
                recommendations='["Restart process", "Set memory limits"]',
                fix_plan='{"steps": ["restart worker"]}',
                fix_risk_level="medium",
            )

            assert "RCAResult" in result
            assert "root_cause_identified" in result
            mock_trigger.assert_called_once_with(issue_id)

    def test_save_fix_plan_triggers_auto_approve(self, db_session, enable_pipeline):
        """save_fix_plan() should call trigger_auto_approve."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)

        with patch("agenticops.services.pipeline_service.trigger_auto_approve") as mock_trigger:
            from agenticops.tools.metadata_tools import save_fix_plan

            result = save_fix_plan(
                health_issue_id=issue_id,
                rca_result_id=rca_id,
                risk_level="L1",
                title="Restart worker process",
                summary="Kill stuck process and restart the service",
                steps='[{"action": "host_command", "command": "systemctl restart worker"}]',
                rollback_plan='{"steps": ["systemctl restart worker"]}',
                pre_checks='[{"check": "verify process stuck"}]',
                post_checks='[{"check": "verify service healthy"}]',
            )

            assert "FixPlan" in result
            assert "fix_planned" in result
            # trigger_auto_approve is called with the new plan's ID
            mock_trigger.assert_called_once()
            plan_id = mock_trigger.call_args[0][0]
            assert isinstance(plan_id, int)

    def test_approve_fix_plan_triggers_auto_execute(self, db_session, enable_pipeline):
        """approve_fix_plan() should call trigger_auto_execute."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L1")

        # Advance issue to fix_planned (already done by _create_fix_plan)
        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_trigger:
            from agenticops.tools.metadata_tools import approve_fix_plan

            result = approve_fix_plan(fix_plan_id=plan_id, approved_by="operator:admin")

            assert "approved" in result
            mock_trigger.assert_called_once_with(plan_id)


class TestFullE2EPipeline:
    """Full end-to-end pipeline simulation with mocked agents.

    Exercises the complete flow: Issue → RCA → SRE → Approve → Execute → Resolve
    with real DB state transitions but mocked LLM agent calls.
    """

    def test_full_pipeline_l1_auto_resolve(self, db_session, enable_pipeline):
        """L1 issue should flow through the entire pipeline automatically.

        Simulates what happens when each agent completes its work:
        1. RCA agent saves result → triggers SRE
        2. SRE agent saves fix plan (L1) → auto-approved → triggers Executor
        3. Executor agent saves execution result → auto-resolves
        """
        # ── Step 1: Create HealthIssue ────────────────────────────────
        issue_id = _create_test_issue(db_session)
        db_session.expire_all()
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "open"
        print(f"\n[1] HealthIssue #{issue_id} created: status=open")

        # ── Step 2: Simulate RCA completion ───────────────────────────
        # Mock the SRE trigger to prevent actual agent call, but capture
        with patch("agenticops.services.pipeline_service.trigger_auto_sre") as mock_sre:
            from agenticops.tools.metadata_tools import save_rca_result

            # Set to investigating first
            issue.status = "investigating"
            db_session.commit()

            rca_result = save_rca_result(
                health_issue_id=issue_id,
                root_cause="Runaway process from bad deployment v2.3",
                confidence=0.92,
                contributing_factors='["Bad deployment v2.3", "No CPU cgroup limits"]',
                recommendations='["Kill process", "Rollback", "Add cgroup limits"]',
                fix_plan='{"steps": [{"action": "host_command", "command": "kill -9 PID"}]}',
                fix_risk_level="medium",
            )
            mock_sre.assert_called_once_with(issue_id)
            print(f"[2] RCA saved: {rca_result}")

        # Verify RCA state
        db_session.expire_all()
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "root_cause_identified"
        rca = db_session.query(RCAResult).filter_by(health_issue_id=issue_id).first()
        assert rca is not None
        rca_id = rca.id
        print(f"[2] Issue status: root_cause_identified, RCA #{rca_id}")

        # ── Step 3: Simulate SRE completion (save fix plan) ──────────
        # Mock both auto_approve and the downstream execute
        with patch("agenticops.services.pipeline_service.trigger_auto_approve") as mock_approve:
            from agenticops.tools.metadata_tools import save_fix_plan

            plan_result = save_fix_plan(
                health_issue_id=issue_id,
                rca_result_id=rca_id,
                risk_level="L1",
                title="Kill runaway process and restart worker",
                summary="SSH to host, kill PID, restart systemd service",
                steps=json.dumps([
                    {"step_index": 1, "action": "host_command", "command": "kill -9 $(pgrep -f worker_v2.3)"},
                    {"step_index": 2, "action": "host_command", "command": "systemctl restart app-worker"},
                ]),
                rollback_plan=json.dumps({"steps": [{"action": "host_command", "command": "systemctl restart app-worker"}]}),
                pre_checks=json.dumps([{"check": "CPU > 90%", "command": "top -bn1 | head -5"}]),
                post_checks=json.dumps([{"check": "CPU < 50%", "command": "top -bn1 | head -5"}]),
            )
            mock_approve.assert_called_once()
            plan_id = mock_approve.call_args[0][0]
            print(f"[3] FixPlan saved: {plan_result}")

        # Verify plan state
        db_session.expire_all()
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "fix_planned"
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "draft"
        assert plan.risk_level == "L1"
        print(f"[3] Issue status: fix_planned, FixPlan #{plan_id} (L1, draft)")

        # ── Step 4: Simulate auto-approve (L1) ──────────────────────
        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)
            mock_exec.assert_called_once_with(plan_id)

        # Verify approval state
        db_session.expire_all()
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "approved"
        assert plan.approved_by == "agent:auto-pipeline"
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "fix_approved"
        print(f"[4] Auto-approved: FixPlan #{plan_id} approved by agent:auto-pipeline")
        print(f"[4] Issue status: fix_approved")

        # ── Step 5: Simulate executor completion ─────────────────────
        from agenticops.tools.metadata_tools import save_execution_result

        exec_result = save_execution_result(
            fix_plan_id=plan_id,
            health_issue_id=issue_id,
            status="succeeded",
            step_results=json.dumps([
                {"step_index": 1, "command": "kill -9 12345", "status": "succeeded", "output": "Process killed", "duration_ms": 500},
                {"step_index": 2, "command": "systemctl restart app-worker", "status": "succeeded", "output": "Service restarted", "duration_ms": 2000},
            ]),
            pre_check_results=json.dumps([{"check": "CPU > 90%", "status": "passed", "output": "CPU: 97.2%"}]),
            post_check_results=json.dumps([{"check": "CPU < 50%", "status": "passed", "output": "CPU: 12.4%"}]),
            duration_ms=5000,
        )
        print(f"[5] Execution saved: {exec_result}")

        # ── Verify final state ───────────────────────────────────────
        db_session.expire_all()
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "resolved", f"Expected 'resolved' but got '{issue.status}'"
        assert issue.resolved_at is not None

        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "executed"

        execution = db_session.query(FixExecution).filter_by(fix_plan_id=plan_id).first()
        assert execution is not None
        assert execution.status == "succeeded"
        assert len(execution.step_results) == 2
        assert len(execution.pre_check_results) == 1
        assert len(execution.post_check_results) == 1

        print(f"[5] Issue status: resolved (resolved_at={issue.resolved_at})")
        print(f"[5] FixPlan status: executed")
        print(f"[5] FixExecution #{execution.id}: succeeded, 2 steps, 5000ms")
        print(f"\n{'='*60}")
        print("E2E PIPELINE TEST PASSED: open → investigating → root_cause_identified")
        print("  → fix_planned → fix_approved → resolved")
        print(f"{'='*60}")

    def test_full_pipeline_l2_stops_at_approval(self, db_session, enable_pipeline):
        """L2 issue should stop at fix_planned — requires human approval."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L2")

        with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
            from agenticops.services.pipeline_service import trigger_auto_approve

            trigger_auto_approve(plan_id)
            mock_exec.assert_not_called()

        db_session.expire_all()
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "draft"  # NOT approved

        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status == "fix_planned"  # Stays here

        print(f"\nL2 pipeline correctly stopped at fix_planned (human approval required)")

    def test_execution_failure_keeps_fix_approved(self, db_session, enable_pipeline):
        """Failed execution should keep issue at fix_approved for retry."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L1")

        # Approve the plan
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        plan.status = "approved"
        plan.approved_by = "agent:auto-pipeline"
        plan.approved_at = datetime.utcnow()
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        issue.status = "fix_approved"
        db_session.commit()

        # Simulate failed execution
        from agenticops.tools.metadata_tools import save_execution_result

        exec_result = save_execution_result(
            fix_plan_id=plan_id,
            health_issue_id=issue_id,
            status="failed",
            step_results=json.dumps([
                {"step_index": 1, "command": "kill -9 PID", "status": "succeeded", "output": "OK"},
                {"step_index": 2, "command": "systemctl restart worker", "status": "failed", "output": "Unit not found"},
            ]),
            error_message="Step 2 failed: systemd unit not found",
            duration_ms=3000,
        )

        db_session.expire_all()
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "failed"

        # Issue should NOT be resolved
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status != "resolved"
        assert issue.resolved_at is None

        execution = db_session.query(FixExecution).filter_by(fix_plan_id=plan_id).first()
        assert execution.status == "failed"
        assert execution.error_message == "Step 2 failed: systemd unit not found"

        print(f"\nExecution failed: issue remains at '{issue.status}' for retry")

    def test_execution_rolled_back(self, db_session, enable_pipeline):
        """Rolled-back execution should mark plan as failed."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L1")

        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        plan.status = "approved"
        plan.approved_by = "agent:auto-pipeline"
        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        issue.status = "fix_approved"
        db_session.commit()

        from agenticops.tools.metadata_tools import save_execution_result

        save_execution_result(
            fix_plan_id=plan_id,
            health_issue_id=issue_id,
            status="rolled_back",
            step_results=json.dumps([
                {"step_index": 1, "status": "succeeded"},
                {"step_index": 2, "status": "failed"},
            ]),
            rollback_results=json.dumps([
                {"step_index": 2, "status": "rolled_back"},
                {"step_index": 1, "status": "rolled_back"},
            ]),
            error_message="Step 2 failed, rollback completed",
        )

        db_session.expire_all()
        execution = db_session.query(FixExecution).filter_by(fix_plan_id=plan_id).first()
        assert execution.status == "rolled_back"
        assert len(execution.rollback_results) == 2

        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "failed"

        issue = db_session.query(HealthIssue).filter_by(id=issue_id).first()
        assert issue.status != "resolved"

        print(f"\nRolled back: plan=failed, issue='{issue.status}'")


class TestGateControls:
    """Test that individual pipeline gates work as kill switches."""

    def test_auto_fix_disabled_blocks_sre(self, db_session, disable_pipeline):
        """auto_fix_enabled=false should block SRE trigger."""
        with patch("agenticops.services.pipeline_service._run_auto_sre") as mock:
            from agenticops.services.pipeline_service import trigger_auto_sre

            trigger_auto_sre(1)
            time.sleep(0.1)
            mock.assert_not_called()

    def test_auto_fix_disabled_blocks_approve(self, db_session, disable_pipeline):
        """auto_fix_enabled=false should block auto-approve."""
        issue_id = _create_test_issue(db_session)
        rca_id = _create_rca_result(db_session, issue_id)
        plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L0")

        from agenticops.services.pipeline_service import trigger_auto_approve

        trigger_auto_approve(plan_id)

        db_session.expire_all()
        plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
        assert plan.status == "draft"  # Not approved

    def test_auto_fix_disabled_blocks_execute(self, db_session, disable_pipeline):
        """auto_fix_enabled=false should block execution trigger."""
        with patch("agenticops.services.pipeline_service._run_auto_execute") as mock:
            from agenticops.services.pipeline_service import trigger_auto_execute

            trigger_auto_execute(42)
            time.sleep(0.1)
            mock.assert_not_called()

    def test_auto_approve_disabled(self, db_session, enable_pipeline):
        """executor_auto_approve_l0_l1=false should skip auto-approval."""
        from agenticops.config import settings

        settings.executor_auto_approve_l0_l1 = False
        try:
            issue_id = _create_test_issue(db_session)
            rca_id = _create_rca_result(db_session, issue_id)
            plan_id = _create_fix_plan(db_session, issue_id, rca_id, risk_level="L0")

            with patch("agenticops.services.pipeline_service.trigger_auto_execute") as mock_exec:
                from agenticops.services.pipeline_service import trigger_auto_approve

                trigger_auto_approve(plan_id)
                mock_exec.assert_not_called()

            db_session.expire_all()
            plan = db_session.query(FixPlan).filter_by(id=plan_id).first()
            assert plan.status == "draft"
        finally:
            settings.executor_auto_approve_l0_l1 = True

    def test_executor_disabled_blocks_execute(self, db_session, enable_pipeline):
        """executor_enabled=false should block execution trigger."""
        from agenticops.config import settings

        settings.executor_enabled = False
        try:
            with patch("agenticops.services.pipeline_service._run_auto_execute") as mock:
                from agenticops.services.pipeline_service import trigger_auto_execute

                trigger_auto_execute(42)
                time.sleep(0.1)
                mock.assert_not_called()
        finally:
            settings.executor_enabled = True


class TestSSHCommandClassification:
    """Verify SSH commands are correctly classified for execution safety."""

    @pytest.mark.parametrize("cmd,expected", [
        ("ssh-add -l", "readonly"),
        ("ssh-keygen -lf /path/key.pub", "readonly"),
        ("ssh-keyscan host.example.com", "readonly"),
        ("sshd -t", "readonly"),
        ("ssh-keygen -R old-host", "write"),
        ("ssh-add ~/.ssh/key.pem", "write"),
        ("scp file.txt user@host:/tmp/", "write"),
        ("rsync -avz /local/ user@host:/remote/", "write"),
    ])
    def test_ssh_classification(self, cmd, expected):
        from agenticops.skills.security import classify_shell_command

        assert classify_shell_command(cmd) == expected
