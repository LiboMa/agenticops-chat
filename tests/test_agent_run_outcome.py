"""MVP-2.9.0 (final review): an agent run that fails is on the issue's timeline.

rca_agent and sre_agent do not raise on a model or tool failure — each returns «… agent error: …» — so the thread
wrappers' «it raised» branch never sees an ordinary failure: the timeline ended at «asked for», the lane vanished and
the page could not tell «failed» from «lost». The agents now record their own failed end: a diagnosis that could not
run, a plan request that ended in an error, a plan request that ended without a plan.
"""
import json
import threading

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_session
from agenticops.services import agent_runs


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/outcome.db")
    monkeypatch.setattr(settings, "auto_fix_enabled", False)
    Base.metadata.create_all(models_mod.get_engine())
    agent_runs.clear()
    yield
    agent_runs.clear()
    models_mod._engine = None


def _issue(status="root_cause_identified"):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status=status, resource_id="i-1")
        s.add(issue); s.flush()
        s.add(RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9))
        s.commit()
        return issue.id
    finally:
        s.close()


def _events(issue_id, event_type):
    s = get_session()
    try:
        return [(e.status, json.loads(e.detail) if isinstance(e.detail, str) else e.detail) for e in
                s.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type=event_type).order_by(PipelineEvent.id)]
    finally:
        s.close()


def _model(monkeypatch, behaviour):
    """Stands in for the model call the agents make (preamble.invoke_with_retry); everything around it is real."""
    import agenticops.agents.preamble as preamble
    monkeypatch.setattr(preamble, "invoke_with_retry", behaviour)


def _throttled(*_a, **_k):
    raise RuntimeError("ThrottlingException: rate exceeded")


def test_a_diagnosis_the_model_could_not_run_is_recorded_as_failed(db, monkeypatch):
    from agenticops.agents.rca_agent import rca_agent
    iid = _issue()
    _model(monkeypatch, _throttled)
    assert rca_agent(issue_id=iid).startswith("RCA agent error")              # it does not raise …
    assert _events(iid, "rca_completed") == [("failed", {"reason": "agent error", "error": "RuntimeError"})]   # … and says so


def test_a_plan_request_the_model_could_not_run_is_recorded_as_failed(db, monkeypatch):
    from agenticops.agents.sre_agent import sre_agent
    iid = _issue()
    _model(monkeypatch, _throttled)
    assert sre_agent(issue_id=iid).startswith("SRE agent error")
    assert _events(iid, "fix_plan_requested") == [("failed", {"reason": "agent error", "error": "RuntimeError"})]


def test_a_plan_request_that_ends_without_a_plan_is_recorded_as_failed(db, monkeypatch):
    from agenticops.agents.sre_agent import sre_agent
    iid = _issue()
    _model(monkeypatch, lambda *_a, **_k: "I could not write a safe plan for this.")
    assert "could not" in sre_agent(issue_id=iid)
    assert _events(iid, "fix_plan_requested") == [("failed", {"reason": "no_plan"})]


def test_a_plan_request_that_saved_a_plan_records_no_failure(db, monkeypatch):
    from agenticops.agents.sre_agent import sre_agent
    from agenticops.services.pipeline_events import log_event
    iid = _issue()

    def writes_a_plan(*_a, **_k):
        s = get_session()
        try:
            rca_id = s.query(RCAResult.id).filter_by(health_issue_id=iid).scalar()
            s.add(FixPlan(health_issue_id=iid, rca_result_id=rca_id, risk_level="L1", title="p", summary="s", status="draft"))
            s.commit()
        finally:
            s.close()
        log_event(iid, "fix_plan_created", "plan", detail={"plan_id": 1})       # what save_fix_plan writes
        return "plan saved"

    _model(monkeypatch, writes_a_plan)
    assert sre_agent(issue_id=iid) == "plan saved"
    assert _events(iid, "fix_plan_requested") == []


def test_a_person_s_request_that_fails_ends_on_the_timeline_through_the_real_agent(db, monkeypatch):
    """The route → the thread → the real rca_agent wrapper, with only the model call failing."""
    from agenticops.web.app import app
    iid = _issue()
    _model(monkeypatch, _throttled)
    assert TestClient(app).post(f"/api/health-issues/{iid}/rca").status_code == 202
    for t in threading.enumerate():
        if t.name.startswith("rca-trigger-"):
            t.join(30)
    assert agent_runs.get(iid) is None
    assert [s for s, _d in _events(iid, "rca_started")] == ["started"]
    assert [s for s, _d in _events(iid, "rca_completed")] == ["failed"]         # once: the wrapper adds no second one
