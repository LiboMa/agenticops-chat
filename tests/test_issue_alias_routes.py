"""The /api/issues/{id} aliases IssueDetail calls must pass the session actor on (2.6.0 d23bce3 gave the
/api/health-issues handlers an `actor` dependency; calling them directly left it a Depends object → 500)."""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, HealthIssue, RCAResult, get_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/alias.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)


def _issue_with_rca():
    s = get_session()
    try:
        i = HealthIssue(title="t", description="d", severity="low", source="test", status="root_cause_identified", resource_id="r")
        s.add(i); s.flush()
        s.add(RCAResult(health_issue_id=i.id, root_cause="x", confidence=0.9)); s.commit()
        return i.id
    finally:
        s.close()


@pytest.mark.parametrize("action", ["generate-fix-plan", "rca"])
def test_the_issue_alias_starts_the_agent_as_the_session_actor(client, action):
    iid = _issue_with_rca()
    with patch("threading.Thread") as thread:
        r = client.post(f"/api/issues/{iid}/{action}")
    assert r.status_code == 202, r.text
    started_as = [a for call in thread.call_args_list for a in call.kwargs.get("args", ())]
    assert "web:anonymous" in started_as   # auth off: the anonymous web actor, never a Depends placeholder


@pytest.mark.parametrize("action", ["generate-fix-plan", "rca"])
def test_the_legacy_anomaly_alias_starts_the_agent_as_the_session_actor(client, action):
    iid = _issue_with_rca()
    with patch("threading.Thread") as thread:
        r = client.post(f"/api/anomalies/{iid}/{action}")
    assert r.status_code == 202, r.text
    assert "web:anonymous" in [a for call in thread.call_args_list for a in call.kwargs.get("args", ())]


def test_the_issue_status_alias_moves_the_issue_as_the_session_actor(client):
    """PUT /api/issues/{id}/status is IssueDetail's «Mark resolved»."""
    from agenticops.services import pipeline_events
    iid = _issue_with_rca()
    with patch.object(pipeline_events, "log_event"):
        r = client.put(f"/api/issues/{iid}/status", json={"status": "resolved"})
    assert r.status_code == 200, r.text
    s = get_session()
    assert s.get(HealthIssue, iid).status == "resolved"
    s.close()


def test_no_route_calls_a_handler_and_leaves_its_depends_parameter_unfilled():
    """A handler called directly from another route gets its Depends(...) DEFAULT, not the resolved value — five
    aliases 500'd that way (actor = a Depends placeholder). Any direct call must pass every Depends parameter."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src/agenticops/web/app.py").read_text(encoding="utf-8")
    funcs = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    bad = []
    for name, fn in funcs.items():
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in funcs and call.func.id != name:
                callee = funcs[call.func.id]
                defaults = callee.args.defaults
                tail = callee.args.args[-len(defaults):] if defaults else []
                depends = [a.arg for a, d in zip(tail, defaults)
                           if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "Depends"]
                if depends and len(call.args) + len(call.keywords) < len(callee.args.args):
                    bad.append(f"{name} → {call.func.id} (unfilled: {depends})")
    assert bad == []
