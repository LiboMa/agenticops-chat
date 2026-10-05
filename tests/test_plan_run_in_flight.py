"""A fix plan's auto-run in flight (2026-10-05 final review C1).

trigger_auto_execute runs the executor in a daemon thread that writes no FixExecution row until the run ends,
so the plan stays 'approved' and the issue 'fix_approved' for the whole run. The one DB-backed, multi-worker
signal that it is running is the issue timeline: the newest `execution_started` for the plan, newer than any
`execution_completed` after it, and younger than executor_total_timeout. POST /fix-plans/{id}/execute refuses
(409) while it holds, so a second executor never runs the same plan alongside the first.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/inflight.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield
    models_mod._engine = None


@pytest.fixture
def client(db):
    from agenticops.web.app import app
    return TestClient(app)


def _plan(status="approved") -> tuple[int, int]:
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_approved",
                            resource_id="r")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s",
                       status=status)
        s.add(plan); s.commit()
        return issue.id, plan.id
    finally:
        s.close()


def _event(issue_id, event_type, ago_s, detail=None, status="started", raw_detail=None):
    s = get_session()
    try:
        s.add(PipelineEvent(health_issue_id=issue_id, event_type=event_type, stage="execution", status=status,
                            detail=raw_detail if raw_detail is not None else (json.dumps(detail) if detail else None),
                            created_at=datetime.now(timezone.utc) - timedelta(seconds=ago_s)))
        s.commit()
    finally:
        s.close()


def _in_flight(plan_id) -> bool:
    from agenticops.services.pipeline_service import plan_run_in_flight
    s = get_session()
    try:
        return plan_run_in_flight(s, plan_id)
    finally:
        s.close()


class TestPlanRunInFlight:
    def test_no_events_is_not_in_flight(self, db):
        _, plan_id = _plan()
        assert _in_flight(plan_id) is False

    def test_a_started_run_without_a_completion_is_in_flight(self, db):
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 60, {"plan_id": plan_id, "executor": "agent:executor"})
        assert _in_flight(plan_id) is True

    def test_a_completion_after_the_start_ends_it(self, db):
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 120, {"plan_id": plan_id})
        _event(issue_id, "execution_completed", 30, {"plan_id": plan_id, "verification": "passed"}, status="succeeded")
        assert _in_flight(plan_id) is False

    def test_a_failed_completion_ends_it(self, db):
        """_run_auto_execute's own event when the executor raised."""
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 120, {"plan_id": plan_id})
        _event(issue_id, "execution_completed", 30, {"plan_id": plan_id}, status="failed")
        assert _in_flight(plan_id) is False

    def test_an_issue_scoped_completion_without_a_plan_id_after_the_start_ends_it(self, db):
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 120, {"plan_id": plan_id})
        _event(issue_id, "execution_completed", 30, None, status="failed")
        assert _in_flight(plan_id) is False

    def test_a_completion_older_than_the_newest_start_does_not_end_it(self, db):
        """An aborted run leaves the plan approved; the retry's start is newer than that completion."""
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 600, {"plan_id": plan_id})
        _event(issue_id, "execution_completed", 500, {"plan_id": plan_id}, status="aborted")
        _event(issue_id, "execution_started", 60, {"plan_id": plan_id})
        assert _in_flight(plan_id) is True

    def test_a_start_older_than_the_executor_timeout_is_stale(self, db):
        from agenticops.config import settings
        issue_id, plan_id = _plan()
        with patch.object(settings, "executor_total_timeout", 600):
            _event(issue_id, "execution_started", 900, {"plan_id": plan_id})
            assert _in_flight(plan_id) is False
            _event(issue_id, "execution_started", 300, {"plan_id": plan_id})
            assert _in_flight(plan_id) is True

    def test_another_plans_and_another_issues_events_are_ignored(self, db):
        issue_id, plan_id = _plan()
        other_issue, other_plan = _plan()
        _event(issue_id, "execution_started", 60, {"plan_id": plan_id + 100})   # a plan id that is not this one
        _event(other_issue, "execution_started", 60, {"plan_id": plan_id})      # this plan's id, another issue
        assert _in_flight(plan_id) is False
        assert _in_flight(other_plan) is False

    def test_a_malformed_detail_is_ignored_and_a_missing_plan_is_not_in_flight(self, db):
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 60, raw_detail="{not json")
        _event(issue_id, "execution_started", 50, raw_detail='["a list"]')
        assert _in_flight(plan_id) is False
        assert _in_flight(plan_id + 999) is False

    def test_the_auto_execute_thread_writes_the_signal_it_reads(self, db):
        """The producer and the reader agree on the event shape: _run_auto_execute's start makes the plan in
        flight while the executor runs, and the thread's own failure event ends it."""
        from agenticops.services import pipeline_service as ps
        _, plan_id = _plan()
        seen = {}

        def executor_agent(fix_plan_id):
            seen["during"] = _in_flight(fix_plan_id)
            raise RuntimeError("boom")

        with patch("agenticops.agents.executor_agent.executor_agent", side_effect=executor_agent), \
             patch("agenticops.services.notification_service.flush_consolidated"):
            ps._run_auto_execute(plan_id)
        assert seen["during"] is True
        assert _in_flight(plan_id) is False


class TestExecuteEndpointRefusesASecondRun:
    def test_409_while_a_run_of_the_plan_is_in_flight(self, client):
        from agenticops.config import settings
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 60, {"plan_id": plan_id})
        with patch.object(settings, "executor_enabled", True):
            r = client.post(f"/api/fix-plans/{plan_id}/execute", json={})
        assert r.status_code == 409
        assert r.json()["detail"] == "A run of this plan is already in progress"
        s = get_session()
        try:
            assert s.query(FixExecution).count() == 0
            assert s.get(FixPlan, plan_id).status == "approved"
            assert s.get(HealthIssue, issue_id).status == "fix_approved"
        finally:
            s.close()

    def test_202_once_the_run_completed_or_went_stale(self, client):
        from agenticops.config import settings
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", 120, {"plan_id": plan_id})
        _event(issue_id, "execution_completed", 60, {"plan_id": plan_id}, status="aborted")
        with patch.object(settings, "executor_enabled", True):
            assert client.post(f"/api/fix-plans/{plan_id}/execute", json={}).status_code == 202
        issue_id, plan_id = _plan()
        _event(issue_id, "execution_started", settings.executor_total_timeout + 60, {"plan_id": plan_id})
        with patch.object(settings, "executor_enabled", True):
            assert client.post(f"/api/fix-plans/{plan_id}/execute", json={}).status_code == 202

    def test_the_existing_checks_keep_their_order(self, client):
        """404 for a missing plan and 400 for a plan that is not approved come first, in flight or not."""
        from agenticops.config import settings
        issue_id, plan_id = _plan(status="executing")
        _event(issue_id, "execution_started", 60, {"plan_id": plan_id})
        with patch.object(settings, "executor_enabled", True):
            assert client.post("/api/fix-plans/99999/execute", json={}).status_code == 404
            assert client.post(f"/api/fix-plans/{plan_id}/execute", json={}).status_code == 400

