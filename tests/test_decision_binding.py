"""MVP-2.9.0 (final review): a decision is bound to what the person was shown.

An approval already carries the plan's content hash. Two other decisions carried nothing. A verdict on a diagnosis
went to «the newest diagnosis» — which, after «diagnose again», is not the one the page may still be showing: the
person judged text the server did not record the judgement against, and «wrong» taught the agent to avoid a
conclusion nobody had read. And «mark resolved» — final, a resolved issue cannot be reopened — went through from
whatever state the issue had reached meanwhile.
"""
import inspect
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, HealthIssue, PipelineEvent, RCAResult, get_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/binding.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _issue(status="root_cause_identified", rcas=2):
    s = get_session()
    try:
        issue = HealthIssue(title="Port 22 open", description="d", severity="high", source="test", status=status, resource_id="sg/sg-1")
        s.add(issue); s.flush()
        ids = []
        for n in range(rcas):
            r = RCAResult(health_issue_id=issue.id, root_cause=f"cause {n + 1}", confidence=0.5,
                          created_at=datetime(2026, 11, 17, 8, n, tzinfo=timezone.utc))
            s.add(r); s.flush(); ids.append(r.id)
        s.commit()
        return issue.id, ids
    finally:
        s.close()


def _rca(rca_id):
    s = get_session()
    try:
        r = s.get(RCAResult, rca_id)
        return r.human_verdict, r.human_note
    finally:
        s.close()


def _events(issue_id, event_type):
    s = get_session()
    try:
        return [json.loads(e.detail) if isinstance(e.detail, str) else e.detail for e in
                s.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type=event_type).order_by(PipelineEvent.id)]
    finally:
        s.close()


# ── a verdict names the diagnosis it is about ──────────────────────────────────────────────────────────────────

def test_a_verdict_on_a_diagnosis_that_is_no_longer_the_newest_is_refused(client):
    iid, (old, new) = _issue()
    with patch("agenticops.memory.agent_memory.save_memory_file") as memory:
        r = client.post(f"/api/health-issues/{iid}/rca-feedback", json={"verdict": "incorrect", "note": "wrong host", "rca_id": old})
    assert r.status_code == 409
    assert (r.json()["code"], r.json()["rca_id"]) == ("rca_changed", new)          # which one is the newest now
    assert _rca(old) == (None, None) and _rca(new) == (None, None)                 # nothing was judged
    assert not memory.called and _events(iid, "rca_human_feedback") == []


def test_a_verdict_on_the_newest_diagnosis_goes_through_and_an_unnamed_one_as_before(client):
    iid, (_old, new) = _issue()
    r = client.post(f"/api/health-issues/{iid}/rca-feedback", json={"verdict": "correct", "rca_id": new})
    assert r.status_code == 201 and r.json()["rca_id"] == new and _rca(new)[0] == "correct"
    iid2, (_o, new2) = _issue()
    assert client.post(f"/api/health-issues/{iid2}/rca-feedback", json={"verdict": "correct"}).status_code == 201
    assert _rca(new2)[0] == "correct"                                                # older clients name none


def test_the_note_of_a_verdict_is_kept_whole_on_the_timeline(client):
    """It was cut to 200 characters there and quoted back as if that were all the person wrote."""
    iid, (_old, new) = _issue()
    note = "because " + "x" * 900
    with patch("agenticops.memory.agent_memory.save_memory_file"):
        client.post(f"/api/health-issues/{iid}/rca-feedback", json={"verdict": "incorrect", "note": note, "rca_id": new})
    assert _events(iid, "rca_human_feedback")[-1]["note"] == note
    with patch("agenticops.memory.agent_memory.save_memory_file"):
        client.post(f"/api/health-issues/{iid}/rca-feedback", json={"verdict": "incorrect", "note": "y" * 5000})
    assert len(_events(iid, "rca_human_feedback")[-1]["note"]) == 2000


# ── a status change can say which status the page showed ───────────────────────────────────────────────────────

def test_a_status_change_from_a_state_the_issue_has_left_is_refused(client):
    iid, _ = _issue("fix_executing")                                # the page showed «fix_executed: mark it resolved»
    r = client.put(f"/api/issues/{iid}/status", json={"status": "resolved", "expected_status": "fix_executed"})
    assert r.status_code == 409 and r.json()["code"] == "status_moved" and r.json()["status"] == "fix_executing"
    s = get_session()
    try:
        assert s.get(HealthIssue, iid).status == "fix_executing"
    finally:
        s.close()


def test_a_status_change_from_the_state_shown_goes_through_and_an_unbound_one_as_before(client):
    iid, _ = _issue("fix_executed")
    assert client.put(f"/api/issues/{iid}/status", json={"status": "resolved", "expected_status": "fix_executed"}).status_code == 200
    iid2, _ = _issue("fix_executed")
    assert client.put(f"/api/anomalies/{iid2}/status", json={"status": "resolved"}).status_code == 200


# ── the two requests that start an agent write to the database: never on the event loop ────────────────────────

def test_the_handlers_that_start_an_agent_do_not_run_on_the_event_loop():
    """They write the start record. On SQLite a writer can wait up to 30 s for the lock; inside an `async def`
    handler that wait stops every chat stream of the one process (CLAUDE.md «Core trust»)."""
    from agenticops.web.app import app
    paths = {"/api/health-issues/{issue_id}/rca", "/api/health-issues/{issue_id}/generate-fix-plan",
             "/api/issues/{issue_id}/rca", "/api/issues/{issue_id}/generate-fix-plan",
             "/api/anomalies/{issue_id}/rca", "/api/anomalies/{issue_id}/generate-fix-plan"}
    found = {r.path: r.endpoint for r in app.routes if getattr(r, "path", None) in paths and "POST" in getattr(r, "methods", ())}
    assert set(found) == paths
    assert [p for p, fn in found.items() if inspect.iscoroutinefunction(fn)] == []


# ── what a dismissal teaches the detect agent stays short ──────────────────────────────────────────────────────

def test_the_reason_copied_into_the_detect_agents_memory_is_capped(client):
    """The memory body goes into the detect agent's system prompt on every run; the timeline keeps the whole text."""
    iid, _ = _issue()
    with patch("agenticops.memory.agent_memory.save_memory_file") as save:
        client.put(f"/api/issues/{iid}/status", json={"status": "dismissed", "note": "n" * 1500})
    body = save.call_args.kwargs["body"]
    assert "User note: " + "n" * 300 + "…" in body and "n" * 301 not in body
    with patch("agenticops.memory.agent_memory.save_memory_file") as save:
        iid2, _ = _issue()
        client.put(f"/api/issues/{iid2}/status", json={"status": "dismissed", "note": "short reason"})
    assert save.call_args.kwargs["body"].endswith("User note: short reason")


# ── an approval's answer says whether the run started ──────────────────────────────────────────────────────────

def _pending_plan():
    from agenticops.models import FixPlan
    from agenticops.services.plan_content import stamp_content
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_planned", resource_id="i-1")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s",
                       status="pending_approval", steps=[{"action": "look", "command": "aws ec2 describe-instances"}])
        s.add(plan); s.flush()
        stamp_content(s, plan); s.commit()
        return plan.id, plan.content_hash
    finally:
        s.close()


def test_the_approve_answer_says_whether_the_run_was_queued(client, monkeypatch):
    """The page says «approving does not run it» from a plan it read a while ago; the executor can be switched on
    in between. What happened is in the answer, so the page does not have to believe what it read."""
    from agenticops.config import settings
    from agenticops.services import pipeline_service
    monkeypatch.setattr(pipeline_service, "_run_auto_execute", lambda *a, **k: None)      # no executor in a test
    monkeypatch.setattr(settings, "auto_fix_enabled", True)
    monkeypatch.setattr(settings, "executor_enabled", True)
    pid, h = _pending_plan()
    r = client.put(f"/api/fix-plans/{pid}/approve", json={"content_hash": h})
    assert r.status_code == 200 and r.json()["run_queued"] is True

    monkeypatch.setattr(settings, "executor_enabled", False)
    pid2, h2 = _pending_plan()
    r2 = client.put(f"/api/fix-plans/{pid2}/approve", json={"content_hash": h2})
    assert r2.status_code == 200 and r2.json()["run_queued"] is False
    assert client.get(f"/api/fix-plans/{pid2}").json()["run_queued"] is None             # only an approval's answer says it
