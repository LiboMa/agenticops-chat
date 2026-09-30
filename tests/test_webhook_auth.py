"""Alert-webhook token check (MVP-2.6.1 spec §3.B.5). With `webhook_secret` set, POST /api/webhooks/alert[/{source}]
needs the shared token (Bearer / X-AIOps-Token / ?token=) or an X-AIOps-Signature HMAC inside the time window, and
is exempt from APIAuthMiddleware's Bearer check; unset, nothing changes and startup logs a WARNING."""
import json
import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agenticops.auth.signatures import sign, token_matches, verify_hmac_signature
from agenticops.config import settings
from agenticops.integrations.alert_processor import AlertProcessResult

SECRET = "s3cret-token"
BODY = {"AlarmName": "EKS-shop-prod-PodRestarts-High", "NewStateValue": "ALARM"}
RAW = json.dumps(BODY).encode()
NOW = 1_790_668_800


# ── auth/signatures ───────────────────────────────────────────────────────────


def test_a_signature_over_the_timestamp_and_body_verifies_inside_the_window():
    sig = sign(SECRET, str(NOW), RAW)
    assert sig.startswith("sha256=") and len(sig) == 7 + 64
    for now in (NOW, NOW + 300, NOW - 300):                      # the window is inclusive, both directions
        assert verify_hmac_signature(SECRET, str(NOW), sig, RAW, window_seconds=300, now=now)


@pytest.mark.parametrize("secret,timestamp,signature,body,now", [
    ("other", str(NOW), None, RAW, NOW),                          # wrong secret
    (SECRET, str(NOW), None, RAW + b" ", NOW),                    # body changed after signing
    (SECRET, str(NOW), None, RAW, NOW + 301),                     # replayed too late
    (SECRET, str(NOW), None, RAW, NOW - 301),                     # clock far ahead of ours
    (SECRET, str(NOW + 1), None, RAW, NOW),                       # timestamp changed after signing
    (SECRET, "not-a-number", None, RAW, NOW),
    (SECRET, "", None, RAW, NOW),
    ("", str(NOW), None, RAW, NOW),                               # no secret configured never verifies
    (SECRET, str(NOW), "", RAW, NOW),
    (SECRET, str(NOW), "deadbeef", RAW, NOW),                     # no sha256= prefix
])
def test_a_signature_that_does_not_match_or_is_stale_is_refused(secret, timestamp, signature, body, now):
    signature = sign(SECRET, str(NOW), RAW) if signature is None else signature
    assert verify_hmac_signature(secret, timestamp, signature, body, window_seconds=300, now=now) is False


def test_token_comparison():
    assert token_matches(SECRET, SECRET)
    assert not token_matches(SECRET, SECRET + "x")
    assert not token_matches(SECRET, "")
    assert not token_matches("", "")                              # an unset secret never matches anything
    assert not token_matches(SECRET, "tökén")                     # non-ASCII input is a mismatch, not a crash


# ── the two intake routes ─────────────────────────────────────────────────────


@pytest.fixture
def intake(monkeypatch):
    """The webhooks router on its own app; process_alert stubbed (the Signal Gate has its own tests)."""
    from agenticops.integrations import alert_processor
    from agenticops.web.routers import webhooks

    calls = []
    monkeypatch.setattr(alert_processor, "process_alert", lambda alert, **kw: calls.append(alert) or
                        AlertProcessResult(action="created", health_issue_id=1, alert_event_id=1, message="ok"))
    monkeypatch.setattr(settings, "alert_pipeline_mode", "event_driven")
    monkeypatch.setattr(settings, "intake_signature_window_seconds", 300)
    app = FastAPI()
    app.include_router(webhooks.router)
    client = TestClient(app)
    client.calls = calls
    return client


def _post(client, path="/api/webhooks/alert/cloudwatch", headers=None, body=RAW):
    return client.post(path, content=body, headers={"Content-Type": "application/json", **(headers or {})})


def test_without_a_secret_nothing_changes(intake, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "")
    assert _post(intake).status_code == 201
    assert _post(intake, "/api/webhooks/alert").status_code == 201


@pytest.mark.parametrize("path", ["/api/webhooks/alert", "/api/webhooks/alert/cloudwatch"])
def test_with_a_secret_a_request_without_a_token_is_401(intake, monkeypatch, path):
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    for headers in ({}, {"X-AIOps-Token": "wrong"}, {"Authorization": "Bearer wrong"}):
        r = _post(intake, path, headers)
        assert (r.status_code, r.json()["detail"]) == (401, "webhook token or signature required"), headers
    assert intake.calls == []                                     # nothing parsed, nothing reached the gate


@pytest.mark.parametrize("where", ["bearer", "header", "query"])
def test_the_token_is_accepted_in_any_of_the_three_places(intake, monkeypatch, where):
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    path, headers = "/api/webhooks/alert/cloudwatch", {}
    if where == "bearer":
        headers = {"Authorization": f"Bearer {SECRET}"}
    elif where == "header":
        headers = {"X-AIOps-Token": SECRET}
    else:
        path += f"?token={SECRET}"
    assert _post(intake, path, headers).status_code == 201
    assert [a.alarm_name for a in intake.calls] == ["EKS-shop-prod-PodRestarts-High"]


def test_a_user_bearer_token_next_to_the_webhook_token_still_passes(intake, monkeypatch):
    """The chaos-lab client sends its session Bearer on every call and the webhook token beside it."""
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    assert _post(intake, headers={"Authorization": "Bearer user-session", "X-AIOps-Token": SECRET}).status_code == 201


def test_an_hmac_signature_is_accepted_and_a_stale_or_forged_one_is_not(intake, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    ts = str(int(time.time()))
    good = {"X-AIOps-Timestamp": ts, "X-AIOps-Signature": sign(SECRET, ts, RAW)}
    assert _post(intake, headers=good).status_code == 201

    stale_ts = str(int(time.time()) - 301)
    stale = {"X-AIOps-Timestamp": stale_ts, "X-AIOps-Signature": sign(SECRET, stale_ts, RAW)}
    other_body = json.dumps({**BODY, "NewStateValue": "OK"}).encode()
    for headers, body in ((stale, RAW), (good, other_body), ({"X-AIOps-Signature": good["X-AIOps-Signature"]}, RAW)):
        assert _post(intake, headers=headers, body=body).status_code == 401
    assert len(intake.calls) == 1


def test_the_check_runs_before_source_validation(intake, monkeypatch):
    """An unauthenticated caller learns nothing about which sources exist."""
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    assert _post(intake, "/api/webhooks/alert/nagios").status_code == 401
    assert _post(intake, "/api/webhooks/alert/nagios", {"X-AIOps-Token": SECRET}).status_code == 400


def test_reading_alert_events_is_not_a_webhook_intake(intake, monkeypatch):
    from agenticops.web.routers.webhooks import is_webhook_intake

    assert is_webhook_intake("POST", "/api/webhooks/alert")
    assert is_webhook_intake("POST", "/api/webhooks/alert/prometheus")
    assert not is_webhook_intake("GET", "/api/webhooks/alert/events")
    assert not is_webhook_intake("GET", "/api/webhooks/alert/events/7")
    assert not is_webhook_intake("POST", "/api/webhooks/alertx")
    assert not is_webhook_intake("POST", "/api/changes/intake")


# ── APIAuthMiddleware exemption ───────────────────────────────────────────────


@pytest.fixture
def guarded(intake):
    """The same app behind APIAuthMiddleware, as api_auth_enabled=true installs it."""
    from agenticops.web.app import APIAuthMiddleware

    intake.app.add_middleware(APIAuthMiddleware)
    return TestClient(intake.app)


def test_with_a_secret_the_middleware_lets_the_intake_through_to_the_token_check(guarded, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    assert _post(guarded, headers={"X-AIOps-Token": SECRET}).status_code == 201
    r = _post(guarded)
    assert (r.status_code, r.json()["detail"]) == (401, "webhook token or signature required")
    r = guarded.get("/api/webhooks/alert/events")                  # still a Bearer-protected read
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required")


def test_without_a_secret_the_middleware_still_demands_a_bearer(guarded, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "")
    r = _post(guarded)
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required")


def test_the_lifted_middleware_still_lets_a_real_session_or_api_key_through(guarded, monkeypatch, tmp_path):
    """Lifting APIAuthMiddleware out of the `if` moved it, nothing more: a real session token and a real aiops_* API
    key still pass a Bearer-protected read, with the caller's user on request.state."""
    import agenticops.models as models_mod
    from fastapi import Request
    from agenticops.auth.models import User
    from agenticops.auth.service import AuthService

    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/webhook-auth.db")
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    AuthService.create_user(email="ops@example.test", password="pw-not-a-secret", name="ops")
    with models_mod.get_db_session() as s:
        user_id = s.query(User.id).filter_by(email="ops@example.test").scalar()
    seen = []

    @guarded.app.get("/api/probe/whoami")
    async def whoami(request: Request):
        # isinstance only: validate_api_key hands back an expired, detached User (reading its columns raises)
        seen.append((isinstance(request.state.user, User), hasattr(request.state, "api_key")))
        return {}

    for token in (AuthService.create_session(user_id), AuthService.create_api_key(user_id, "probe")):
        bearer = {"Authorization": f"Bearer {token}"}
        assert guarded.get("/api/webhooks/alert/events", headers=bearer).status_code == 200
        assert guarded.get("/api/probe/whoami", headers=bearer).status_code == 200
    assert seen == [(True, False), (True, True)]
    r = guarded.get("/api/probe/whoami", headers={"Authorization": "Bearer not-a-session"})
    assert (r.status_code, r.json()["detail"]) == (401, "Invalid or expired token.")


# ── startup ───────────────────────────────────────────────────────────────────


def test_startup_warns_only_when_no_secret_is_set(monkeypatch, caplog):
    from agenticops.web.routers.webhooks import warn_if_unauthenticated

    monkeypatch.setattr(settings, "webhook_secret", "")
    warn_if_unauthenticated()
    assert "webhook_secret is not set" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    warn_if_unauthenticated()
    assert caplog.text == ""


def test_the_settings_keys_exist():
    import yaml

    with open("config/settings.yaml") as f:
        doc = yaml.safe_load(f)
    assert doc["webhook_secret"] == "" and doc["intake_signature_window_seconds"] == 300
