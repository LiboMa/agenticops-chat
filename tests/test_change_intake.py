# tests/test_change_intake.py
"""External change intake POST /api/changes/intake and the webhook actor's ceiling (MVP-2.6.1 Plan D, spec §3.D.3):
off (404) until change_intake_secret is set, HMAC over timestamp + body (401), the requester is
webhook:<system>, a still-open request for the same external ticket comes back (200), and webhook:* can never
approve or execute — not even in shadow mode."""
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from fastapi import FastAPI
from starlette.testclient import TestClient

from agenticops.auth import authz
from agenticops.auth.actor import Actor, im_actor, webhook_actor
from agenticops.auth.signatures import sign
from agenticops.config import settings
from agenticops.models import Base, ChangeRequest, CloudAccount, get_session
from agenticops.services import change_service as cs

SECRET = "intake-test-secret"
TAG = "aws ec2 create-tags --resources i-0abc --tags Key=Env,Value=prod"
BODY = {"title": "tag web", "description": "add Env=prod", "account": "dev", "target_hints": ["i-0abc"],
        "proposed_steps": [{"action": "tag", "command": TAG}], "requested_by": "carol",
        "external_ref": {"system": "jira", "ticket_id": "OPS-42", "url": "https://jira.example.com/OPS-42"}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/intake.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "change_intake_secret", SECRET)
    monkeypatch.setattr(settings, "intake_signature_window_seconds", 300)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from agenticops.web.app import app
    with patch.object(cs, "start_review") as review, patch.object(cs, "notify_change_requested"):
        c = TestClient(app)  # bare — no `with`, so the lifespan never starts
        c.review = review
        yield c


def _post(client, body=None, *, secret=SECRET, ts=None, raw=None, headers=None):
    raw = raw if raw is not None else json.dumps(BODY if body is None else body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    signed = {"X-AIOps-Timestamp": ts, "X-AIOps-Signature": sign(secret, ts, raw)}
    return client.post("/api/changes/intake", content=raw,
                       headers={"Content-Type": "application/json", **(signed if headers is None else headers)})


# ── authentication ──────────────────────────────────────────────────────────

def test_intake_is_off_until_a_secret_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "change_intake_secret", "")
    r = _post(client, secret="")
    assert r.status_code == 404 and "change_intake_secret" in r.json()["detail"]


@pytest.mark.parametrize("case", ["unsigned", "wrong-secret", "stale", "from-the-future", "tampered", "bad-timestamp"])
def test_a_missing_wrong_or_stale_signature_is_401(client, db, case):
    now = int(time.time())
    raw = json.dumps(BODY).encode()
    if case == "unsigned":
        r = _post(client, headers={})
    elif case == "wrong-secret":
        r = _post(client, secret="not-the-secret")
    elif case in ("stale", "from-the-future"):
        r = _post(client, ts=now - 301 if case == "stale" else now + 301)
    elif case == "tampered":  # signed one body, sent another
        r = _post(client, raw=raw.replace(b"OPS-42", b"OPS-43"),
                  headers={"X-AIOps-Timestamp": str(now), "X-AIOps-Signature": sign(SECRET, str(now), raw)})
    else:
        r = _post(client, headers={"X-AIOps-Timestamp": "soon", "X-AIOps-Signature": sign(SECRET, "soon", raw)})
    assert r.status_code == 401
    assert db.query(ChangeRequest).count() == 0


# ── the request it opens ────────────────────────────────────────────────────

def test_a_signed_request_opens_a_change_as_the_external_system(client, db):
    r = _post(client)
    assert r.status_code == 201, r.text
    cr = r.json()
    assert (cr["requested_by"], cr["source"], cr["requester_user_id"]) == ("webhook:jira", "webhook", None)
    assert cr["external_ref"] == {**BODY["external_ref"], "requested_by": "carol"}  # a claimed name, not an identity
    assert cr["proposed_steps"] == [{"action": "tag", "command": TAG}] and cr["target_hints"] == ["i-0abc"]
    row = db.get(ChangeRequest, cr["id"])
    assert (row.account_id, row.external_system, row.external_ticket_id) == (1, "jira", "OPS-42")
    client.review.assert_called_once_with(cr["id"], sync=False)


def test_the_same_open_ticket_returns_the_same_request(client, db):
    first = _post(client).json()["id"]
    again = _post(client, ts=int(time.time()) - 10)  # a redelivery, signed again
    assert (again.status_code, again.json()["id"]) == (200, first)
    assert client.review.call_count == 1
    other = _post(client, {**BODY, "external_ref": {"system": "servicenow", "ticket_id": "OPS-42"}})
    assert other.status_code == 201 and other.json()["id"] != first  # the ticket id is per system
    db.get(ChangeRequest, first).status = "rejected"
    db.commit()
    reopened = _post(client)
    assert reopened.status_code == 201 and reopened.json()["id"] not in (first, other.json()["id"])


@pytest.mark.parametrize("raw,where", [
    (json.dumps({k: v for k, v in BODY.items() if k != "external_ref"}).encode(), ["body", "external_ref"]),
    (json.dumps({**BODY, "external_ref": {"system": "Jira!", "ticket_id": "1"}}).encode(),
     ["body", "external_ref", "system"]),
    (json.dumps({**BODY, "proposed_steps": [{"action": "tag", "command": ""}]}).encode(),
     ["body", "proposed_steps", 0, "command"]),
    (b"{not json", ["body"]),
    (json.dumps(BODY).encode().replace(b"tag web", b"tag \xff web"), ["body"]),  # not UTF-8
])
def test_a_signed_but_invalid_body_is_422(client, db, raw, where):
    r = _post(client, raw=raw)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"][:len(where)] == where
    assert db.query(ChangeRequest).count() == 0


def test_an_unknown_account_is_422(client, db):
    r = _post(client, {**BODY, "account": "nope"})
    assert r.status_code == 422 and "account 'nope' not found" in r.json()["detail"]


# ── APIAuthMiddleware ───────────────────────────────────────────────────────

@pytest.fixture
def guarded(client):
    """The changes router behind APIAuthMiddleware, as api_auth_enabled=true installs it."""
    from agenticops.web.app import APIAuthMiddleware
    from agenticops.web.routers import changes

    app = FastAPI()
    app.include_router(changes.router)
    app.add_middleware(APIAuthMiddleware)
    return TestClient(app)


def test_the_middleware_lets_only_a_signed_intake_through(guarded, monkeypatch):
    assert _post(guarded).status_code == 201
    assert _post(guarded, secret="not-the-secret").status_code == 401  # the HMAC is its authentication
    r = guarded.get("/api/changes")
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required")
    monkeypatch.setattr(settings, "change_intake_secret", "")
    r = _post(guarded, secret="")
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required")


@pytest.mark.parametrize("host", ["x/?", "evil/?a="])
def test_a_host_header_carrying_a_path_cannot_skip_the_bearer_check(guarded, db, host):
    """request.url is rebuilt from the Host header (`http://x/?/api/changes` has path '/'); routing uses
    scope['path'], so the middleware must decide on that too — else every protected route is open."""
    r = guarded.get("/api/changes", headers={"host": host})
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required"), r.text
    raw = json.dumps(BODY).encode()
    r = guarded.post("/api/changes", content=raw, headers={"host": host, "Content-Type": "application/json"})
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required"), r.text
    assert db.query(ChangeRequest).count() == 0


def test_only_the_exact_intake_route_is_exempt(guarded, db):
    """A trailing slash or a GET is not the intake: a valid signature does not lift the Bearer check there."""
    raw = json.dumps(BODY).encode()
    ts = str(int(time.time()))
    signed = {"X-AIOps-Timestamp": ts, "X-AIOps-Signature": sign(SECRET, ts, raw), "Content-Type": "application/json"}
    for r in (guarded.post("/api/changes/intake/", content=raw, headers=signed),
              guarded.get("/api/changes/intake", headers=signed)):
        assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required"), r.text
    assert db.query(ChangeRequest).count() == 0


# ── the webhook actor's ceiling ─────────────────────────────────────────────

@pytest.mark.parametrize("permission", ["plan.approve", "change.approve", "plan.execute", "change.execute"])
@pytest.mark.parametrize("subject", [None, SimpleNamespace(requested_by="user:alice", risk_level="L0")])
def test_a_webhook_actor_can_never_approve_or_execute_even_in_shadow(permission, subject):
    policy = authz.get_rbac_policy(reload=True)
    allowed, reason, rule, always = policy.decide(webhook_actor("jira"), permission, subject)
    assert (allowed, always) == (False, True)
    if subject is not None:  # without one, an earlier always-rule may deny first (fail-closed) — still enforced
        assert (rule, reason) == ("no-webhook-approve-or-execute", f"webhook actors may never {permission}")
    with patch.object(settings, "rbac_enforce", False), patch("agenticops.audit.service.AuditService.log"):
        with pytest.raises(authz.AuthzDenied):
            authz.check(webhook_actor("jira"), permission, subject=subject)
    assert policy.decide(webhook_actor("jira"), "change.request", None)[0] is True  # it may still open one


def test_a_missing_flag_alone_is_still_only_a_shadow_deny():
    """The reorder that lets an always-rule beat the matrix leaves a plain matrix deny as it was."""
    cr = SimpleNamespace(requested_by="user:alice", risk_level="L1")
    policy = authz.get_rbac_policy(reload=True)
    assert policy.decide(im_actor("feishu", "ou_1"), "change.approve", cr) == (
        False, "missing permission flag(s): write", None, False)
    with patch.object(settings, "rbac_enforce", False), patch("agenticops.audit.service.AuditService.log"):
        authz.check(im_actor("feishu", "ou_1"), "change.approve", subject=cr)  # no raise
    assert policy.decide(Actor("user", "bob", permissions=("read", "write")), "change.approve", cr)[0] is True


def test_the_service_refuses_a_webhook_approval_with_403(client):
    cr_id = _post(client).json()["id"]
    for call in (lambda: cs.approve(cr_id, actor=webhook_actor("jira"), reason="ok", content_hash="0" * 64),
                 lambda: cs.request_execution(cr_id, actor=webhook_actor("jira"))):
        with patch.object(settings, "executor_enabled", True), \
             pytest.raises(cs.ChangeForbidden, match="webhook actors may never") as denied:
            call()
        assert denied.value.status_code == 403


def test_the_rule_type_is_validated_strictly_and_the_shipped_file_matches_the_defaults():
    from agenticops.config import PROJECT_ROOT
    rule = {"name": "r", "permission": "plan.approve", "type": "deny_actor_kind", "actor_kind": "webhook"}
    base = {**authz.DEFAULT_POLICY, "rules": [rule]}
    assert authz.validate_rbac(base) == []
    assert authz.validate_rbac({**base, "rules": [{k: v for k, v in rule.items() if k != "actor_kind"}]}) == [
        "r: 'actor_kind' (string) is required"]
    assert "does not apply to deny_actor_kind" in authz.validate_rbac(
        {**base, "rules": [{**rule, "risk_levels": ["L3"]}]})[0]
    # a misspelt kind would silently disable an always-deny; a stray field reads as if it narrowed the rule
    risk_rule = {**rule, "type": "deny_actor_kind_when_risk_in", "risk_levels": ["L3"]}
    for r in (rule, risk_rule):
        assert authz.validate_rbac({**base, "rules": [{**r, "actor_kind": "webhooks"}]}) == [
            "r: unknown actor_kind 'webhooks' (expected one of agent, cli, im, user, web, webhook)"]
        assert authz.validate_rbac({**base, "rules": [{**r, "field": "requested_by"}]}) == [
            f"r: 'field' does not apply to {r['type']}"]
    shipped = yaml.safe_load((PROJECT_ROOT / "config" / "rbac.yaml").read_text(encoding="utf-8"))
    assert authz.validate_rbac(shipped) == []
    assert shipped["rules"] == authz.DEFAULT_POLICY["rules"]
