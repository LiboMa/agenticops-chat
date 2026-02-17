"""Tests for SRE Agent and FixPlan metadata tools."""

import json
import pytest
from datetime import datetime

from agenticops.models import (
    Base,
    FixPlan,
    HealthIssue,
    RCAResult,
    get_session,
)


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Reset singleton engine so each test gets a fresh DB
    models_mod._engine = None

    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def health_issue(db_session):
    """Create a test HealthIssue."""
    issue = HealthIssue(
        resource_id="i-test123",
        severity="high",
        source="cloudwatch_alarm",
        title="High CPU on i-test123",
        description="CPU utilization exceeded 90%",
        status="root_cause_identified",
    )
    db_session.add(issue)
    db_session.commit()
    return issue


@pytest.fixture
def rca_result(db_session, health_issue):
    """Create a test RCAResult."""
    rca = RCAResult(
        health_issue_id=health_issue.id,
        root_cause="Runaway process consuming CPU",
        confidence=0.85,
        contributing_factors=["No CPU limits", "Auto-scaling disabled"],
        recommendations=["Kill runaway process", "Enable auto-scaling"],
        fix_plan={"steps": ["SSH to instance", "Kill process"]},
        fix_risk_level="medium",
        model_id="test-model",
    )
    db_session.add(rca)
    db_session.commit()
    return rca


# ============================================================================
# FixPlan model tests
# ============================================================================


class TestFixPlanModel:
    """Tests for the FixPlan database model."""

    def test_create_fix_plan(self, db_session, health_issue, rca_result):
        """Test creating a FixPlan record."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L2",
            title="Restart runaway process",
            summary="Kill the runaway process and restart the application",
            steps=[
                {"action": "SSH to instance", "command": "ssh ec2-user@i-test123"},
                {"action": "Kill process", "command": "kill -9 <PID>"},
            ],
            rollback_plan={"description": "No rollback needed — process already failing"},
            estimated_impact="Brief service interruption during restart",
            pre_checks=["Verify instance is reachable via SSH"],
            post_checks=["Verify CPU drops below 80%", "Verify application health check passes"],
        )
        db_session.add(plan)
        db_session.commit()

        assert plan.id is not None
        assert plan.risk_level == "L2"
        assert plan.status == "draft"
        assert len(plan.steps) == 2
        assert plan.approved_by is None

    def test_fix_plan_relationship(self, db_session, health_issue, rca_result):
        """Test FixPlan -> HealthIssue relationship."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L1",
            title="Adjust alarm threshold",
            summary="Lower the CPU alarm threshold",
            steps=[{"action": "Update alarm", "command": "aws cloudwatch put-metric-alarm ..."}],
        )
        db_session.add(plan)
        db_session.commit()

        db_session.refresh(health_issue)
        assert len(health_issue.fix_plans) == 1
        assert health_issue.fix_plans[0].title == "Adjust alarm threshold"


# ============================================================================
# save_fix_plan tool tests
# ============================================================================


class TestSaveFixPlan:
    """Tests for save_fix_plan metadata tool."""

    def test_save_basic_plan(self, db_session, health_issue, rca_result):
        """Test saving a basic fix plan."""
        from agenticops.tools.metadata_tools import save_fix_plan

        result = save_fix_plan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L1",
            title="Adjust CPU alarm threshold",
            summary="Lower the CPU alarm threshold from 90% to 80%",
            steps='[{"action": "Update alarm", "command": "aws cloudwatch put-metric-alarm --alarm-name cpu-high --threshold 80"}]',
        )

        assert "FixPlan #" in result
        assert "L1" in result
        assert "fix_planned" in result

        plan = db_session.query(FixPlan).first()
        assert plan is not None
        assert plan.risk_level == "L1"
        assert len(plan.steps) == 1

        db_session.refresh(health_issue)
        assert health_issue.status == "fix_planned"

    def test_invalid_risk_level(self, db_session, health_issue, rca_result):
        """Test that invalid risk levels are rejected."""
        from agenticops.tools.metadata_tools import save_fix_plan

        result = save_fix_plan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L5",
            title="Test",
            summary="Test",
        )

        assert "Invalid risk_level" in result

    def test_invalid_issue_id(self, db_session, rca_result):
        """Test saving plan for non-existent issue."""
        from agenticops.tools.metadata_tools import save_fix_plan

        result = save_fix_plan(
            health_issue_id=9999,
            rca_result_id=rca_result.id,
            risk_level="L0",
            title="Test",
            summary="Test",
        )

        assert "not found" in result

    def test_invalid_rca_id(self, db_session, health_issue):
        """Test saving plan for non-existent RCA result."""
        from agenticops.tools.metadata_tools import save_fix_plan

        result = save_fix_plan(
            health_issue_id=health_issue.id,
            rca_result_id=9999,
            risk_level="L0",
            title="Test",
            summary="Test",
        )

        assert "not found" in result


# ============================================================================
# get_fix_plan tool tests
# ============================================================================


class TestGetFixPlan:
    """Tests for get_fix_plan metadata tool."""

    def test_get_existing_plan(self, db_session, health_issue, rca_result):
        """Test retrieving an existing fix plan."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L2",
            title="Resize instance",
            summary="Upgrade from t3.micro to t3.small",
            steps=[{"action": "Resize", "command": "aws ec2 modify-instance-attribute ..."}],
            rollback_plan={"steps": ["Resize back to t3.micro"]},
            estimated_impact="Instance reboot required (~2 min downtime)",
        )
        db_session.add(plan)
        db_session.commit()

        from agenticops.tools.metadata_tools import get_fix_plan

        result = get_fix_plan(health_issue_id=health_issue.id)
        data = json.loads(result)

        assert data["risk_level"] == "L2"
        assert data["title"] == "Resize instance"
        assert len(data["steps"]) == 1
        assert data["status"] == "draft"

    def test_get_plan_not_found(self, db_session):
        """Test retrieving plan for non-existent issue."""
        from agenticops.tools.metadata_tools import get_fix_plan

        result = get_fix_plan(health_issue_id=9999)
        assert "No fix plan found" in result


# ============================================================================
# approve_fix_plan tool tests
# ============================================================================


class TestApproveFixPlan:
    """Tests for approve_fix_plan metadata tool."""

    def test_approve_l1_plan(self, db_session, health_issue, rca_result):
        """Test approving an L1 plan (can be auto-approved)."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L1",
            title="Update tag",
            summary="Fix resource tagging",
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        from agenticops.tools.metadata_tools import approve_fix_plan

        result = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre_agent")
        assert "approved" in result.lower()

        db_session.refresh(plan)
        assert plan.status == "approved"
        assert plan.approved_by == "agent:sre_agent"
        assert plan.approved_at is not None

    def test_l3_requires_human_approval(self, db_session, health_issue, rca_result):
        """Test that L3 plans require human approval."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L3",
            title="Failover database",
            summary="Trigger RDS failover to standby",
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        from agenticops.tools.metadata_tools import approve_fix_plan

        result = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre_agent")
        assert "pending_approval" in result
        assert "human" in result.lower()

        db_session.refresh(plan)
        assert plan.status == "pending_approval"

    def test_human_can_approve_l3(self, db_session, health_issue, rca_result):
        """Test that a human can approve L3 plans."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L3",
            title="Failover database",
            summary="Trigger RDS failover",
            status="pending_approval",
        )
        db_session.add(plan)
        db_session.commit()

        from agenticops.tools.metadata_tools import approve_fix_plan

        result = approve_fix_plan(fix_plan_id=plan.id, approved_by="john.doe@company.com")
        assert "approved" in result.lower()

        db_session.refresh(plan)
        assert plan.status == "approved"
        assert plan.approved_by == "john.doe@company.com"

    def test_approve_nonexistent_plan(self, db_session):
        """Test approving non-existent plan."""
        from agenticops.tools.metadata_tools import approve_fix_plan

        result = approve_fix_plan(fix_plan_id=9999, approved_by="test")
        assert "not found" in result

    def test_approve_already_approved(self, db_session, health_issue, rca_result):
        """Test approving an already-approved plan."""
        plan = FixPlan(
            health_issue_id=health_issue.id,
            rca_result_id=rca_result.id,
            risk_level="L0",
            title="Verify metric",
            summary="Check if metric recovered",
            status="approved",
            approved_by="test",
            approved_at=datetime.utcnow(),
        )
        db_session.add(plan)
        db_session.commit()

        from agenticops.tools.metadata_tools import approve_fix_plan

        result = approve_fix_plan(fix_plan_id=plan.id, approved_by="test2")
        assert "already approved" in result


# ============================================================================
# SRE Agent tool list tests
# ============================================================================


class TestSREAgentToolList:
    """Tests to verify the SRE agent has the correct tools configured."""

    def test_sre_agent_imports(self):
        """Test that sre_agent module imports correctly."""
        from agenticops.agents.sre_agent import sre_agent, SRE_SYSTEM_PROMPT
        assert callable(sre_agent)
        assert "READ-ONLY" in SRE_SYSTEM_PROMPT
        assert "NEVER execute fixes" in SRE_SYSTEM_PROMPT
        assert "save_fix_plan" in SRE_SYSTEM_PROMPT

    def test_sre_prompt_has_risk_levels(self):
        """Test that SRE system prompt defines all risk levels."""
        from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
        assert "L0" in SRE_SYSTEM_PROMPT
        assert "L1" in SRE_SYSTEM_PROMPT
        assert "L2" in SRE_SYSTEM_PROMPT
        assert "L3" in SRE_SYSTEM_PROMPT
