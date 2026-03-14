"""Tests for one-issue-one-fix-plan consolidation (replace mode).

Verifies:
- save_fix_plan() dedup: creates new, updates draft, rejects locked, allows after terminal
- trigger_auto_sre() guard: skips when active plan exists
- API guards: 409 on active/locked plans

Run:
    pytest tests/test_fix_plan_consolidation.py -v
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import (
    Base,
    FixPlan,
    HealthIssue,
    RCAResult,
    FIXPLAN_TERMINAL_STATUSES,
    FIXPLAN_REPLACEABLE_STATUSES,
    FIXPLAN_LOCKED_STATUSES,
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
    db_url = f"sqlite:///{tmp_path}/test_consolidation.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def issue_and_rca(db_session):
    """Create a HealthIssue and RCAResult for testing."""
    issue = HealthIssue(
        title="OOM Kill on pod-abc",
        description="Pod killed due to memory limit",
        severity="high",
        source="prometheus",
        status="root_cause_identified",
        resource_id="pod-abc",
    )
    db_session.add(issue)
    db_session.flush()

    rca = RCAResult(
        health_issue_id=issue.id,
        root_cause="Memory limit too low",
        confidence=0.9,
    )
    db_session.add(rca)
    db_session.commit()

    return issue.id, rca.id


# ── Status constant tests ────────────────────────────────────────────


class TestStatusConstants:
    def test_terminal_statuses(self):
        assert FIXPLAN_TERMINAL_STATUSES == {"executed", "failed", "rejected"}

    def test_replaceable_statuses(self):
        assert FIXPLAN_REPLACEABLE_STATUSES == {"draft"}

    def test_locked_statuses(self):
        assert FIXPLAN_LOCKED_STATUSES == {"pending_approval", "approved", "executing"}

    def test_no_overlap(self):
        all_sets = [FIXPLAN_TERMINAL_STATUSES, FIXPLAN_REPLACEABLE_STATUSES, FIXPLAN_LOCKED_STATUSES]
        for i, a in enumerate(all_sets):
            for b in all_sets[i + 1:]:
                assert a.isdisjoint(b), f"Overlap found: {a & b}"


# ── save_fix_plan() dedup tests ──────────────────────────────────────


class TestSaveFixPlanDedup:

    @patch("agenticops.services.notification_service.notify_fix_planned", new=lambda *a, **kw: None)
    @patch("agenticops.services.pipeline_service.trigger_auto_approve", new=lambda *a, **kw: None)
    def _call_save(self, issue_id, rca_id, title="Fix OOM", risk="L1"):
        from agenticops.tools.metadata_tools import save_fix_plan
        return save_fix_plan(
            health_issue_id=issue_id,
            rca_result_id=rca_id,
            risk_level=risk,
            title=title,
            summary="Increase memory limit",
            steps=json.dumps([{"action": "patch deployment", "command": "kubectl set resources"}]),
            rollback_plan=json.dumps({"description": "revert deployment"}),
            estimated_impact="No downtime",
            pre_checks=json.dumps(["verify pod running"]),
            post_checks=json.dumps(["verify pod healthy"]),
        )

    def test_save_creates_new_when_none(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca
        result = self._call_save(issue_id, rca_id)
        assert "saved" in result
        assert "FixPlan #" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 1
        assert plans[0].status == "draft"

    def test_save_updates_draft_in_place(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        # Create first plan
        result1 = self._call_save(issue_id, rca_id, title="First attempt")
        plan_id = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first().id

        # Save again — should update, not create new
        result2 = self._call_save(issue_id, rca_id, title="Consolidated fix")
        assert "UPDATED" in result2

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 1
        assert plans[0].id == plan_id
        assert plans[0].title == "Consolidated fix"

    def test_save_rejects_when_pending_approval(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        self._call_save(issue_id, rca_id)
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        plan.status = "pending_approval"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="Another plan")
        assert "Cannot create a new plan" in result
        assert "pending_approval" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 1

    def test_save_rejects_when_approved(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        # Create and approve a plan
        self._call_save(issue_id, rca_id)
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        plan.status = "approved"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="Second plan")
        assert "Cannot create a new plan" in result
        assert "approved" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 1

    def test_save_rejects_when_executing(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        self._call_save(issue_id, rca_id)
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        plan.status = "executing"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="Third plan")
        assert "Cannot create a new plan" in result
        assert "executing" in result

    def test_save_allows_new_after_failed(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        self._call_save(issue_id, rca_id, title="First plan")
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        first_id = plan.id
        plan.status = "failed"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="Retry plan")
        assert "saved" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 2
        new_plan = [p for p in plans if p.id != first_id][0]
        assert new_plan.title == "Retry plan"
        assert new_plan.status == "draft"

    def test_save_allows_new_after_executed(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        self._call_save(issue_id, rca_id)
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        plan.status = "executed"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="New plan after execute")
        assert "saved" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 2

    def test_save_allows_new_after_rejected(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        self._call_save(issue_id, rca_id)
        plan = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).first()
        plan.status = "rejected"
        db_session.commit()

        result = self._call_save(issue_id, rca_id, title="New plan after reject")
        assert "saved" in result

        plans = db_session.query(FixPlan).filter_by(health_issue_id=issue_id).all()
        assert len(plans) == 2


# ── trigger_auto_sre() guard tests ───────────────────────────────────


class TestTriggerAutoSreGuard:

    def test_skips_when_active_plan_exists(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca
        from agenticops.config import settings
        settings.auto_fix_enabled = True

        # Create an active plan
        plan = FixPlan(
            health_issue_id=issue_id,
            rca_result_id=rca_id,
            risk_level="L1",
            title="Existing plan",
            summary="Already here",
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        with patch("agenticops.services.pipeline_service.threading.Thread") as mock_thread:
            from agenticops.services.pipeline_service import trigger_auto_sre
            trigger_auto_sre(issue_id)
            mock_thread.assert_not_called()

    def test_proceeds_when_no_active_plan(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca
        from agenticops.config import settings
        settings.auto_fix_enabled = True

        with patch("agenticops.services.pipeline_service.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            from agenticops.services.pipeline_service import trigger_auto_sre
            trigger_auto_sre(issue_id)
            mock_thread.assert_called_once()

    def test_proceeds_when_only_terminal_plans(self, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca
        from agenticops.config import settings
        settings.auto_fix_enabled = True

        for status in FIXPLAN_TERMINAL_STATUSES:
            plan = FixPlan(
                health_issue_id=issue_id,
                rca_result_id=rca_id,
                risk_level="L1",
                title=f"Plan ({status})",
                summary="Done",
                status=status,
            )
            db_session.add(plan)
        db_session.commit()

        with patch("agenticops.services.pipeline_service.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            from agenticops.services.pipeline_service import trigger_auto_sre
            trigger_auto_sre(issue_id)
            mock_thread.assert_called_once()


# ── API guard tests ──────────────────────────────────────────────────


class TestAPIGuards:

    @pytest.fixture
    def client(self, db_session):
        from fastapi.testclient import TestClient
        from agenticops.web.app import app
        return TestClient(app)

    def test_api_create_409_on_active(self, client, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        # Create an active plan
        plan = FixPlan(
            health_issue_id=issue_id,
            rca_result_id=rca_id,
            risk_level="L1",
            title="Active plan",
            summary="In progress",
            status="pending_approval",
        )
        db_session.add(plan)
        db_session.commit()

        resp = client.post("/api/fix-plans", json={
            "health_issue_id": issue_id,
            "rca_result_id": rca_id,
            "risk_level": "L1",
            "title": "Duplicate plan",
            "summary": "Should fail",
            "steps": [],
            "rollback_plan": {},
            "estimated_impact": "",
            "pre_checks": [],
            "post_checks": [],
        })
        assert resp.status_code == 409
        assert "active FixPlan" in resp.json()["detail"]

    def test_api_generate_409_on_locked(self, client, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        plan = FixPlan(
            health_issue_id=issue_id,
            rca_result_id=rca_id,
            risk_level="L2",
            title="Locked plan",
            summary="Being approved",
            status="approved",
        )
        db_session.add(plan)
        db_session.commit()

        resp = client.post(f"/api/health-issues/{issue_id}/generate-fix-plan")
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"]

    def test_api_generate_ok_on_draft(self, client, db_session, issue_and_rca):
        issue_id, rca_id = issue_and_rca

        # Create a draft plan — should NOT block generation (SRE will update it)
        plan = FixPlan(
            health_issue_id=issue_id,
            rca_result_id=rca_id,
            risk_level="L1",
            title="Draft plan",
            summary="Draft",
            status="draft",
        )
        db_session.add(plan)
        db_session.commit()

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            resp = client.post(f"/api/health-issues/{issue_id}/generate-fix-plan")
            assert resp.status_code == 202
