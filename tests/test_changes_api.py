"""Change Management Web API (MVP-2.6.0, Plan B Task 11).

/api/changes lifecycle + timeline, /api/command-audits, the audit read gate, the settings security
toggles, change search, and change plans carrying their change request's account.
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import call, patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import (
    Base, ChangeRequest, CloudAccount, CloudResource, CommandAudit, FixPlan, HealthIssue, RCAResult, get_session,
)

ALICE = Actor("user", "alice", 1, ("read", "write"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/capi.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    # _planned() must stop at 'planned' whatever the local settings.yaml says
    monkeypatch.setattr(settings, "change_auto_approve_standard", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit(); s.close()
    yield TestClient(app)   # bare — no `with`, so the lifespan (schedulers, executor service) never starts


@pytest.fixture
def settings_io():
    """PATCH /api/settings must never write the real config/settings.yaml nor list Bedrock models."""
    with patch("agenticops.config.save_to_yaml") as save, \
         patch("agenticops.services.model_service.get_model_presets", return_value=[]):
        yield save


def _seen(cr_id):
    """The content hash of the change's implementation plan, as the approver is shown it (spec §3.D.1)."""
    from agenticops.services.plan_content import current_hash
    s = get_session()
    try:
        plan = (s.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change")
                .order_by(FixPlan.id.desc()).first())
        return current_hash(s, plan)
    finally:
        s.close()


def _account_id(name):
    s = get_session()
    try:
        return s.query(CloudAccount.id).filter_by(name=name).scalar()
    finally:
        s.close()


def _user_id(email):
    from agenticops.auth.models import User
    s = get_session()
    try:
        return s.query(User.id).filter_by(email=email).scalar()
    finally:
        s.close()


def _token(email, *, admin):
    """A real session token for a new user (AuthService.create_user returns a detached row — re-read the id)."""
    from agenticops.auth.service import AuthService
    AuthService.create_user(email=email, password="pw-not-a-secret", name=email.split("@")[0], is_admin=admin)
    return AuthService.create_session(_user_id(email))


def _planned():
    """Drive a CR to 'planned' through the service (SRE mocked away)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=ALICE, title="Tag web",
                                      description="add Env=prod", account_name="dev", targets=["i-0abc"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    s = get_session()
    s.add(FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                  steps=[{"command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                  post_checks=[{"check": "present", "command": "aws ec2 describe-tags"}], status="draft"))
    s.commit(); s.close()
    with patch.object(cs, "notify_change_pending_approval"):
        cs.submit_review(cr["id"], verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=Actor("agent", "sre"))
    return cr["id"]


def _draft(title="t", description="d"):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        return cs.create_change_request(source="web", actor=ALICE, title=title, description=description, start_review=False)


def _fix_plan_in(account_id, title="fix plan"):
    """A fix plan whose HealthIssue lives in `account_id` → (plan id, issue id)."""
    s = get_session()
    try:
        issue = HealthIssue(account_id=account_id, title="t", description="d", severity="low", source="test",
                            status="fix_planned", resource_id="i-0abc")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title=title, summary="s", status="draft")
        s.add(plan); s.commit()
        return plan.id, issue.id
    finally:
        s.close()


# ── /api/changes ──────────────────────────────────────────────────────

def test_create_lists_and_detail(client):
    with patch("agenticops.services.change_service.start_review") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"):
        r = client.post("/api/changes", json={"title": "Tag web", "description": "add Env=prod", "account_name": "dev",
                                              "targets": ["i-0abc"], "requested_change_type": "normal"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["requested_by"] == "web:anonymous" and body["source"] == "web"
    sr.assert_called_once_with(body["id"], sync=False)
    assert client.get("/api/changes").json()[0]["id"] == body["id"]
    assert client.get("/api/changes?status=planned").json() == []
    d = client.get(f"/api/changes/{body['id']}").json()
    assert d["plans"] == [] and d["executions"] == [] and d["target_hints"] == ["i-0abc"]
    assert client.get("/api/changes/9999").status_code == 404


def test_create_records_the_api_source_for_api_key_callers(client):
    """source='api' iff the caller signed in with an aiops_* API key (APIAuthMiddleware leaves it on
    request.state.api_key); a session-token user — the Web UI — stays 'web'."""
    from fastapi import Request
    from agenticops.web import deps
    from agenticops.web.app import app

    def api_key_caller(request: Request):
        request.state.api_key = SimpleNamespace(permissions=["read", "write"])  # as APIAuthMiddleware sets it
        return ALICE

    body = {"title": "t", "description": "d"}
    try:
        with patch("agenticops.services.change_service.start_review"), \
             patch("agenticops.services.change_service.notify_change_requested"):
            app.dependency_overrides[deps.current_actor] = lambda: ALICE
            session_user = client.post("/api/changes", json=body)
            app.dependency_overrides[deps.current_actor] = api_key_caller
            key_user = client.post("/api/changes", json=body)
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    assert (session_user.status_code, session_user.json()["source"]) == (201, "web")
    assert (key_user.status_code, key_user.json()["source"]) == (201, "api")


def test_validation_errors(client):
    assert client.post("/api/changes", json={"title": "", "description": "x"}).status_code == 422
    assert client.post("/api/changes", json={"title": "t", "description": "d", "requested_change_type": "urgent"}).status_code == 422
    with patch("agenticops.services.change_service.notify_change_requested"):
        r = client.post("/api/changes", json={"title": "t", "description": "d", "account_name": "nope"})
    assert r.status_code == 422 and "account" in r.json()["detail"]


def test_list_inputs_are_validated(client):
    r = client.get("/api/changes?status=bogus")
    assert r.status_code == 422 and "invalid status 'bogus'" in r.json()["detail"]
    assert client.get("/api/changes?status=").status_code == 200  # empty = no filter, as in change_service
    assert client.get("/api/changes?period=1y").status_code == 422
    assert client.get("/api/changes?limit=0").status_code == 422
    assert client.get("/api/command-audits?limit=0").status_code == 422


def test_disabled_returns_404(client):
    """The flag check runs before parameter/body validation: invalid input gets the same 404, not a 422."""
    from agenticops.config import settings
    calls = [("get", "/api/changes", None), ("post", "/api/changes", {"title": "t", "description": "d"}),
             ("get", "/api/changes/1", None), ("get", "/api/changes/1/timeline", None),
             ("post", "/api/changes/1/approve", {"reason": "r"}), ("post", "/api/changes/1/reject", {"reason": "r"}),
             ("post", "/api/changes/1/cancel", {"reason": "r"}), ("post", "/api/changes/1/clarify", {"message": "m"}),
             ("post", "/api/changes/1/review", None), ("post", "/api/changes/1/execute", None),
             ("post", "/api/changes/1/resolve-review", {"outcome": "completed", "reason": "r"}),
             # invalid query / body / path — each a 422 while the flag is on
             ("get", "/api/changes?limit=0", None), ("post", "/api/changes/1/approve", {}),
             ("get", "/api/changes/abc", None)]
    with patch.object(settings, "change_management_enabled", False):
        answers = [(method, url, client.request(method.upper(), url, json=body)) for method, url, body in calls]
    assert [(m, u, r.status_code) for m, u, r in answers
            if r.status_code != 404 or "disabled" not in r.json()["detail"]] == []


def test_approve_requires_reason_and_binds_identity(client):
    cr_id = _planned()
    assert client.post(f"/api/changes/{cr_id}/approve", json={}).status_code == 422
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "reviewed", "content_hash": _seen(cr_id)})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"] == "web:anonymous"
    assert client.post(f"/api/changes/{cr_id}/approve", json={"reason": "again", "content_hash": _seen(cr_id)}).status_code == 409


def test_sod_403_when_enforced(client):
    """SoD needs identified actors (the anonymous web actor is exempt by ruling): request AND approve as the
    same authenticated user by making current_actor resolve to that user. Both denial rows name the SoD rule,
    and a different approver holding `write` passes under enforce — the 403 is the SoD verdict, not a
    permission miss."""
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    from agenticops.web import deps
    from agenticops.web.app import app
    cr2 = _draft()
    with cs._session() as s:
        row = s.get(ChangeRequest, cr2["id"]); cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        # approve() needs the active change plan a positive review leaves behind (else 409, not the SoD verdict)
        s.add(FixPlan(plan_kind="change", change_request_id=cr2["id"], risk_level="L1", title="p", summary="s",
                      steps=[{"command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                      post_checks=[{"check": "present", "command": "aws ec2 describe-tags"}], status="pending_approval"))
    control = _planned()  # also requested by ALICE
    bob = Actor("user", "bob", 2, ("read", "write"))
    app.dependency_overrides[deps.current_actor] = lambda: ALICE
    try:
        with patch.object(settings, "rbac_enforce", True):
            r = client.post(f"/api/changes/{cr2['id']}/approve", json={"reason": "self", "content_hash": _seen(cr2['id'])})
        assert r.status_code == 403
        with patch.object(settings, "rbac_enforce", False):
            r = client.post(f"/api/changes/{cr2['id']}/approve", json={"reason": "self (shadow)", "content_hash": _seen(cr2['id'])})
        assert r.status_code == 200 and r.json()["approved_by"] == "user:alice"  # shadow mode: allowed, audited
        app.dependency_overrides[deps.current_actor] = lambda: bob
        with patch.object(settings, "rbac_enforce", True):
            r = client.post(f"/api/changes/{control}/approve", json={"reason": "four eyes", "content_hash": _seen(control)})
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"] == "user:bob"
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    s = get_session()
    try:
        denials = sorted((a.action, a.entity_id, a.details["rule"])
                         for a in s.query(AuditLog).filter(AuditLog.action.like("authz.denied%")).all())
    finally:
        s.close()
    rule = "sod-change-approver-not-requester"
    assert denials == [("authz.denied", str(cr2["id"]), rule), ("authz.denied_shadow", str(cr2["id"]), rule)]


def test_reject_cancel_clarify_review(client):
    from agenticops.services import change_service as cs
    cr_id = _planned()
    with patch.object(cs, "notify_change_result"):
        r = client.post(f"/api/changes/{cr_id}/reject", json={"reason": "no"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    cr = _draft(description="vague")
    assert client.post(f"/api/changes/{cr['id']}/cancel", json={"reason": "oops"}).status_code == 200
    cr3 = _draft(description="vague")
    with patch("agenticops.services.change_service.start_review") as sr:
        assert client.post(f"/api/changes/{cr3['id']}/review").status_code == 202
    sr.assert_called_once()
    with cs._session() as s:
        row = s.get(ChangeRequest, cr3["id"]); cs.transition_change(row, "under_review"); cs.transition_change(row, "needs_clarification")
    with patch("agenticops.services.change_service.start_review") as sr2:
        r = client.post(f"/api/changes/{cr3['id']}/clarify", json={"message": "it is i-0abc"})
    assert r.status_code == 202 and sr2.called


def test_execute_and_timeline(client):
    from agenticops.config import settings
    cr_id = _planned()
    client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": _seen(cr_id)})
    with patch.object(settings, "executor_enabled", True):
        r = client.post(f"/api/changes/{cr_id}/execute")
    assert r.status_code == 202 and r.json()["status"] == "pending" and r.json()["executed_by"] == "web:anonymous"
    d = client.get(f"/api/changes/{cr_id}").json()
    assert d["status"] == "executing" and d["plans"][0]["plan_kind"] == "change" and len(d["executions"]) == 1
    assert d["plans"][0]["account_id"] == d["account_id"] == _account_id("dev")  # a plan carries its CR's account
    tl = client.get(f"/api/changes/{cr_id}/timeline").json()
    assert {e["kind"] for e in tl} == {"event", "audit"} and any(e["type"] == "change.approved" for e in tl)
    assert client.get("/api/changes/9999/timeline").status_code == 404


def test_detail_carries_the_last_policy_decision(client):
    from agenticops.services.pipeline_events import log_event
    cr_id = _planned()
    pd = client.get(f"/api/changes/{cr_id}").json()["policy_decision"]
    assert isinstance(pd["action"], str) and pd["action"]
    log_event(None, "policy_decision", "approval", "block", detail={"policy_decision": {"action": "block"}},
              change_request_id=cr_id)
    assert client.get(f"/api/changes/{cr_id}").json()["policy_decision"] == {"action": "block"}
    assert client.get(f"/api/changes/{_draft()['id']}").json()["policy_decision"] is None


def test_resolve_review(client):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr_id = _planned()
    client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": _seen(cr_id)})
    with patch.object(settings, "executor_enabled", True):
        plan_id = client.post(f"/api/changes/{cr_id}/execute").json()["fix_plan_id"]
    with patch.object(cs, "notify_change_result"):
        cs.on_execution_result(plan_id, "succeeded", post_check_results=[])
    assert client.post(f"/api/changes/{cr_id}/resolve-review", json={"outcome": "maybe", "reason": "x"}).status_code == 422
    with patch.object(cs, "notify_change_result"):
        r = client.post(f"/api/changes/{cr_id}/resolve-review", json={"outcome": "completed", "reason": "checked in console"})
    assert r.status_code == 200 and r.json()["status"] == "completed"


# ── /api/command-audits + the audit read gate ─────────────────────────

def test_command_audits_endpoint(client):
    s = get_session()
    s.add(CommandAudit(actor="cli:m", tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed", change_request_id=3))
    s.add(CommandAudit(actor="cli:m", tool="run_on_host", tier="write", command="systemctl restart x", outcome="refused", reason="change_required"))
    s.commit(); s.close()
    r = client.get("/api/command-audits")
    assert r.status_code == 200 and len(r.json()) == 2
    assert len(client.get("/api/command-audits?outcome=refused").json()) == 1
    assert client.get("/api/command-audits?change_request_id=3").json()[0]["command"] == "aws ec2 create-tags"


def test_audit_reads_open_when_auth_off(client):
    for url in ("/api/audit", "/api/audit/stats", "/api/command-audits", "/api/audit/entity/change_request/1"):
        assert client.get(url).status_code == 200, url


def test_audit_reads_need_identity_when_auth_on(client, monkeypatch):
    """Auth on → a HARD check independent of rbac_enforce: shadow mode must not widen who reads the audit trail."""
    from agenticops.config import settings
    user = {"Authorization": f"Bearer {_token('bob@example.com', admin=False)}"}
    admin = {"Authorization": f"Bearer {_token('root@example.com', admin=True)}"}
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    for url in ("/api/command-audits", "/api/audit", "/api/audit/stats"):
        assert client.get(url).status_code == 401, url
        assert client.get(url, headers={"Authorization": "Bearer not-a-token"}).status_code == 401, url
        assert client.get(url, headers=user).status_code == 403, url
        assert client.get(url, headers=admin).status_code == 200, url
    assert client.get("/api/audit/entity/change_request/1").status_code == 401
    assert client.get("/api/audit/entity/change_request/1", headers=user).status_code == 200


def test_audit_query_rows_are_readable_after_its_session_closed(client):
    from agenticops.audit.service import AuditService
    AuditService.log("change.requested", "change_request", "9", actor="user:alice", details={"k": 1})
    rows = AuditService.query(entity_type="change_request", entity_id="9")
    assert [(r.action, r.actor, r.details) for r in rows] == [("change.requested", "user:alice", {"k": 1})]


def test_entity_audit_history_pages(client):
    from agenticops.audit.models import AuditLog
    now = datetime.now(timezone.utc)
    s = get_session()
    s.add(AuditLog(timestamp=now - timedelta(minutes=5), action="change.requested", entity_type="change_request", entity_id="7", details={}))
    s.add(AuditLog(timestamp=now - timedelta(minutes=1), action="change.approved", entity_type="change_request", entity_id="7", details={}))
    s.commit(); s.close()
    newer = client.get("/api/audit/entity/change_request/7?limit=1")
    older = client.get("/api/audit/entity/change_request/7?limit=1&offset=1")
    assert newer.status_code == 200 and [e["action"] for e in newer.json()] == ["change.approved"]
    assert older.status_code == 200 and [e["action"] for e in older.json()] == ["change.requested"]


def test_audit_ledger_reaches_90_days(client):
    for url in ("/api/audit", "/api/audit/stats"):
        assert client.get(f"{url}?hours=2160").status_code == 200, url
        assert client.get(f"{url}?hours=2161").status_code == 422, url


# ── PATCH /api/settings security toggles ──────────────────────────────

def _settings_audits(*fields):
    """Every PATCH /api/settings audit row as a tuple of `fields` (default: what changed, by whom)."""
    from agenticops.audit.models import AuditLog
    fields = fields or ("action", "entity_id", "actor", "old_values", "new_values")
    s = get_session()
    try:
        return [tuple(getattr(a, f) for f in fields)
                for a in s.query(AuditLog).filter_by(entity_type="system", entity_name="settings").all()]
    finally:
        s.close()


def test_settings_security_toggle_applies_persists_and_audits(client, settings_io):
    from agenticops.config import settings
    r = client.patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 200 and settings.rbac_enforce is True
    body = r.json()
    assert body["rbac_enforce"] is True and body["change_auto_approve_standard"] is False
    assert body["change_management_enabled"] is True
    settings_io.assert_called_once_with({"rbac_enforce": True})
    assert _settings_audits() == [("update", "rbac_enforce", "web:anonymous", {"rbac_enforce": False}, {"rbac_enforce": True})]


def test_settings_toggle_yaml_failure_applies_nothing_and_a_retry_heals(client, settings_io):
    """The audit rows are written, then the yaml, then the rows commit, all BEFORE the in-memory flip: a failed
    yaml write rolls the rows back and leaves the old value live, so an identical retry still sees the change
    and redoes it."""
    from agenticops.config import settings
    from agenticops.web.app import app
    client = TestClient(app, raise_server_exceptions=False)  # same DB; a failed write answers 500 instead of raising
    settings_io.side_effect = OSError("read-only config mount")
    assert client.patch("/api/settings", json={"rbac_enforce": True}).status_code == 500
    assert settings.rbac_enforce is False and _settings_audits() == []
    settings_io.assert_called_once_with({"rbac_enforce": True})
    settings_io.side_effect = None
    settings_io.reset_mock()
    r = client.patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 200 and settings.rbac_enforce is True
    settings_io.assert_called_once_with({"rbac_enforce": True})
    assert _settings_audits() == [("update", "rbac_enforce", "web:anonymous", {"rbac_enforce": False}, {"rbac_enforce": True})]


def test_settings_toggle_audit_failure_applies_nothing_and_a_retry_heals(client, settings_io):
    from agenticops.audit.service import AuditService
    from agenticops.config import settings
    from agenticops.web.app import app
    client = TestClient(app, raise_server_exceptions=False)  # same DB; a failed write answers 500 instead of raising
    with patch.object(AuditService, "log", side_effect=RuntimeError("audit store down")) as log:
        assert client.patch("/api/settings", json={"rbac_enforce": True}).status_code == 500
    assert [c.args[:3] for c in log.call_args_list] == [("update", "system", "rbac_enforce")]  # the toggle's own row
    assert settings.rbac_enforce is False
    settings_io.assert_not_called()
    r = client.patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 200 and settings.rbac_enforce is True
    settings_io.assert_called_once_with({"rbac_enforce": True})
    assert _settings_audits() == [("update", "rbac_enforce", "web:anonymous", {"rbac_enforce": False}, {"rbac_enforce": True})]


@contextmanager
def _commit_fails():
    """get_db_session whose commit fails after the flush (SQLite busy past its timeout, disk I/O, a PostgreSQL
    connection lost after the flush): the real one rolls back and re-raises."""
    from sqlalchemy.exc import OperationalError
    from agenticops.models import get_db_session

    def _commit():
        raise OperationalError("COMMIT", {}, Exception("database is locked"))
    with get_db_session() as s:
        s.commit = _commit
        yield s


def test_settings_toggle_commit_failure_restores_the_yaml_and_a_retry_heals(client, settings_io):
    """A commit that fails after the yaml write puts the old value back in the yaml: no audit row, the old value
    live, and no toggle in settings.yaml that a restart would turn on."""
    from agenticops.config import settings
    from agenticops.web.app import app
    with patch("agenticops.web.app.get_db_session", _commit_fails):
        r = TestClient(app, raise_server_exceptions=False).patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 500
    assert settings_io.call_args_list == [call({"rbac_enforce": True}), call({"rbac_enforce": False})]
    assert settings.rbac_enforce is False and _settings_audits() == []
    settings_io.reset_mock()
    r = client.patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 200 and settings.rbac_enforce is True
    settings_io.assert_called_once_with({"rbac_enforce": True})
    assert _settings_audits() == [("update", "rbac_enforce", "web:anonymous", {"rbac_enforce": False}, {"rbac_enforce": True})]


def test_settings_toggle_failed_restore_is_logged_and_the_commit_error_stands(client, settings_io, caplog):
    """The restore is best effort: when it fails too, an ERROR names the key, and the request still fails with
    the commit's own error, not the restore's."""
    from sqlalchemy.exc import OperationalError
    from agenticops.config import settings
    from agenticops.web.app import app
    settings_io.side_effect = [None, OSError("read-only config mount")]
    with patch("agenticops.web.app.get_db_session", _commit_fails), \
         caplog.at_level(logging.ERROR, logger="agenticops.web.app"):
        r = TestClient(app, raise_server_exceptions=False).patch("/api/settings", json={"rbac_enforce": True})
    assert r.status_code == 500
    [rec] = [rec for rec in caplog.records if rec.name == "agenticops.web.app" and rec.levelno == logging.ERROR]
    assert "rbac_enforce" in rec.getMessage() and isinstance(rec.exc_info[1], OSError)
    assert settings.rbac_enforce is False and _settings_audits() == []
    settings_io.side_effect = [None, OSError("read-only config mount")]
    with patch("agenticops.web.app.get_db_session", _commit_fails), pytest.raises(OperationalError):
        client.patch("/api/settings", json={"rbac_enforce": True})  # the fixture's client re-raises the app's error


def test_settings_unchanged_toggle_writes_nothing(client, settings_io):
    assert client.patch("/api/settings", json={"rbac_enforce": False}).status_code == 200
    settings_io.assert_not_called()
    assert _settings_audits() == []


def test_settings_security_toggle_must_be_boolean(client, settings_io, monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "auto_rca_enabled", True)
    r = client.patch("/api/settings", json={"rbac_enforce": "yes"})
    assert r.status_code == 400 and r.json()["detail"] == "rbac_enforce must be a boolean"
    r = client.patch("/api/settings", json={"auto_rca_enabled": False, "change_auto_approve_standard": 1})
    assert r.status_code == 400 and settings.auto_rca_enabled is True  # a refused body applies nothing
    assert settings.rbac_enforce is False and settings.change_auto_approve_standard is False
    settings_io.assert_not_called()


def test_settings_security_toggle_needs_admin_when_auth_on(client, settings_io, monkeypatch):
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(settings, "auto_rca_enabled", True)
    user = {"Authorization": f"Bearer {_token('bob@example.com', admin=False)}"}
    admin = {"Authorization": f"Bearer {_token('root@example.com', admin=True)}"}
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    body = {"auto_rca_enabled": False, "rbac_enforce": True}
    assert client.patch("/api/settings", json=body).status_code == 401
    assert client.patch("/api/settings", json=body, headers=user).status_code == 403
    assert settings.auto_rca_enabled is True and settings.rbac_enforce is False  # BOTH unchanged
    settings_io.assert_not_called()
    assert _settings_audits() == []
    # the admin as APIAuthMiddleware + current_actor resolve them (the middleware is installed only at import)
    root = Actor("user", "root@example.com", _user_id("root@example.com"), ("admin", "read", "write"))
    app.dependency_overrides[deps.current_actor] = lambda: root
    try:
        r = client.patch("/api/settings", json=body, headers=admin)
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    assert r.status_code == 200 and settings.auto_rca_enabled is False and settings.rbac_enforce is True
    assert root.user_id and _settings_audits("entity_id", "actor", "user_id") == [
        ("rbac_enforce", "user:root@example.com", root.user_id)]


# ── Change plans: search + account ────────────────────────────────────

def test_search_labels_change_plans_and_finds_change_requests(client):
    from agenticops.config import settings
    fix_plan_id, issue_id = _fix_plan_in(_account_id("dev"), title="fix zeta")
    cr = _draft(title="zeta rollout")
    s = get_session()
    cp = FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="change zeta", summary="s", status="draft")
    s.add(cp); s.commit(); change_plan_id = cp.id; s.close()
    res = client.get("/api/search?q=zeta").json()["results"]
    assert {i["id"]: (i["entity_type"], i["parent_id"]) for i in res["fix_plans"]} == {
        fix_plan_id: ("fix_plan", issue_id), change_plan_id: ("change_plan", cr["id"])}
    assert [(i["id"], i["entity_type"], i["parent_id"]) for i in res["change_requests"]] == [(cr["id"], "change_request", None)]
    with patch.object(settings, "change_management_enabled", False):
        res = client.get("/api/search?q=zeta").json()["results"]
    # flag off: neither a change request nor a change plan — both would link to change pages whose API 404s
    assert "change_requests" not in res
    assert [(i["id"], i["entity_type"]) for i in res["fix_plans"]] == [(fix_plan_id, "fix_plan")]


def test_fix_plan_lists_place_change_plans_in_their_request_account(client):
    from agenticops.services import change_service as cs
    s = get_session()
    s.add(CloudAccount(name="prod", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])); s.commit(); s.close()
    dev, prod = _account_id("dev"), _account_id("prod")
    cr_id = _planned()
    with cs._session() as s:
        change_plan_id = s.query(FixPlan.id).filter_by(change_request_id=cr_id).scalar()
    fix_plan_id, _ = _fix_plan_in(dev)
    assert {p["id"]: p["account_id"] for p in client.get("/api/fix-plans").json()} == {change_plan_id: dev, fix_plan_id: dev}
    rows = client.get(f"/api/fix-plans?account_id={dev}").json()
    assert {p["id"] for p in rows} == {change_plan_id, fix_plan_id} and all(p["account_id"] == dev for p in rows)
    assert [p["id"] for p in client.get(f"/api/fix-plans?kind=change&account_id={dev}").json()] == [change_plan_id]
    assert client.get(f"/api/fix-plans?account_id={prod}").json() == []
    assert client.get(f"/api/fix-plans/{change_plan_id}").json()["account_id"] == dev


def test_fix_plan_reads_decode_legacy_string_encoded_json(client):
    """Legacy rows (dev box #74/#80) hold their JSON columns as JSON *strings*; the strict response
    schema turned every fix-plan list containing one into a 500 (Fix Plans tab stuck on Loading)."""
    plan_id, issue_id = _fix_plan_in(_account_id("dev"))
    s = get_session()
    try:
        p = s.get(FixPlan, plan_id)
        p.steps = '[{"step": 0, "action": "decommission"}]'
        p.rollback_plan = '{"path_a": "restore"}'
        p.post_checks = '["alb gone"]'
        p.pre_checks = "not json"
        s.commit()
    finally:
        s.close()
    listed = client.get("/api/fix-plans?kind=fix")
    assert listed.status_code == 200
    (row,) = listed.json()
    assert row["steps"] == [{"step": 0, "action": "decommission"}]
    assert row["rollback_plan"] == {"path_a": "restore"}
    assert row["post_checks"] == ["alb gone"]
    assert row["pre_checks"] == ["not json"]
    assert client.get(f"/api/fix-plans/{plan_id}").json()["steps"] == [{"step": 0, "action": "decommission"}]
    assert client.get(f"/api/health-issues/{issue_id}/fix-plans").status_code == 200


def test_fix_plan_response_wraps_undecodable_or_missing_json_columns():
    from agenticops.web.schemas import FixPlanResponse
    base = dict(id=1, risk_level="L1", title="t", summary="s", estimated_impact="", status="draft",
                approved_by=None, approved_at=None, created_at=datetime.now(timezone.utc))
    r = FixPlanResponse.model_validate({**base, "steps": None, "pre_checks": '"[\\"a\\"]"',
                                        "post_checks": {"k": 1}, "rollback_plan": "undo by hand"})
    assert (r.steps, r.pre_checks, r.post_checks, r.rollback_plan) == ([], ["a"], [{"k": 1}], {"raw": "undo by hand"})


def test_cancel_change_execution_authorizes_on_change_execute(client):
    """(g) Cancelling a running CHANGE execution authorizes on change.execute (not change.cancel): a
    write caller cancels (200 + one plan.execution_cancelled row, plan_kind=change); a reader is 403."""
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    from agenticops.models import FixExecution
    from agenticops.web import deps
    from agenticops.web.app import app
    reader = Actor("user", "reader", 9, ("read",))
    writer = Actor("user", "wanda", 10, ("read", "write"))
    s = get_session()
    try:
        cr = ChangeRequest(title="t", description="d", requested_by="user:alice", status="executing",
                           account_id=_account_id("dev"))
        s.add(cr); s.flush()
        plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                       status="executing", rollback_plan={"steps": ["undo"]}, post_checks=[{"check": "c"}])
        s.add(plan); s.flush()
        ex = FixExecution(fix_plan_id=plan.id, status="running", executed_by="user:bob")
        s.add(ex); s.commit()
        pid, ex_id = plan.id, ex.id
    finally:
        s.close()
    # a read-only caller under enforce is refused; nothing is cancelled
    app.dependency_overrides[deps.current_actor] = lambda: reader
    try:
        with patch.object(settings, "rbac_enforce", True):
            assert client.post(f"/api/fix-executions/{ex_id}/cancel").status_code == 403
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    # a change.execute holder cancels (change.execute, NOT change.cancel — cancel here means abort the run)
    app.dependency_overrides[deps.current_actor] = lambda: writer
    try:
        with patch.object(settings, "rbac_enforce", True):
            assert client.post(f"/api/fix-executions/{ex_id}/cancel").status_code == 200
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    s = get_session()
    try:
        rows = s.query(AuditLog).filter_by(action="plan.execution_cancelled").all()
        assert len(rows) == 1
        assert rows[0].entity_id == str(pid)
        assert rows[0].details["plan_kind"] == "change" and rows[0].details["execution_id"] == ex_id
    finally:
        s.close()


# ── G15 FR-5: the create schema caps free-text inputs (422 before the service) ──

def test_create_rejects_oversized_inputs_at_the_schema(client):
    """FR-5: ChangeRequestCreate caps description/justification/targets, so an over-cap body is a 422 at
    schema validation and the service is never entered (no notify patch needed). On BASE it had no caps."""
    assert client.post("/api/changes", json={"title": "t", "description": "x" * 8001}).status_code == 422
    assert client.post("/api/changes", json={"title": "t", "description": "d", "justification": "y" * 2001}).status_code == 422
    assert client.post("/api/changes", json={"title": "t", "description": "d", "targets": [f"i-{i}" for i in range(21)]}).status_code == 422
    assert client.post("/api/changes", json={"title": "t", "description": "d", "targets": ["z" * 201]}).status_code == 422
