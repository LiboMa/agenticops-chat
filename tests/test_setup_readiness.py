"""MVP-2.9.0 N23 (the 2.8.0 spec's S6): one answer to «how far is this installation set up?» — and a record of the
last time each account's connection and the main model were actually checked. «Configured» and «verified» are two
things: a check counts only for the credentials / model it was made with."""
import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: F401 — imported at collection (the auth middleware is added only when auth is on at import)

URL = "/api/setup/readiness"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/setup.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    for flag in ("executor_enabled", "auto_fix_enabled", "executor_auto_approve_l0_l1", "change_auto_approve_standard"):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "agent_main_model_id", "global.anthropic.claude-opus-5-5")
    monkeypatch.setattr(settings, "bedrock_region", "us-east-1")
    monkeypatch.setattr("agenticops.notify.im_config.load_channels", lambda: [
        SimpleNamespace(name="ops", is_enabled=True), SimpleNamespace(name="old", is_enabled=False)])
    models_mod.init_db()

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, settings=settings, monkeypatch=monkeypatch)


def _account(name="prod", enabled=True, regions=("us-east-1", "eu-west-1"), role="arn:aws:iam::111111111111:role/ops"):
    from agenticops.models import CloudAccount, get_db_session
    with get_db_session() as s:
        row = CloudAccount(name=name, provider="aws", is_enabled=enabled, regions=list(regions),
                           credential_source_type="assume_role", credentials={"role_arn": role})
        s.add(row)
        s.flush()
        return row.id


def _test(env, headers, account_id, result):
    with patch("agenticops.credentials.session_factory.SessionFactory.test_connection", return_value=result):
        return env.client.post(f"/api/accounts/{account_id}/test", headers=headers)


OK = {"success": True, "identity": "arn:aws:sts::111111111111:assumed-role/ops/x", "account_id": "111111111111", "error": None}


def _no(error):
    return {"success": False, "identity": None, "account_id": None, "error": error}


# ── who may read it ───────────────────────────────────────────────────────────────────────────────────────────

def test_it_needs_a_signed_in_person(env):
    assert env.client.get(URL).status_code == 401


def test_an_empty_installation(env):
    body = env.client.get(URL, headers=env.login("root@x", is_admin=True)).json()
    assert body["accounts"] == {"state": "missing", "enabled": 0, "regions": 0, "items": []}
    assert body["model"] == {"state": "configured", "model_id": "global.anthropic.claude-opus-5-5", "region": "us-east-1", "check": None}
    assert body["notifications"] == {"state": "optional", "channels": 1}          # the enabled ones
    assert body["can_verify"] is True and body["generated_at"].endswith("Z")


# ── cloud accounts: configured is not connected ───────────────────────────────────────────────────────────────

def test_an_account_is_connected_only_after_its_connection_was_tested(env):
    h = env.login("root@x", is_admin=True)
    pk = _account()
    _account("off", enabled=False)                                            # a disabled account is not counted
    acc = env.client.get(URL, headers=h).json()["accounts"]
    assert (acc["state"], acc["enabled"], acc["regions"]) == ("configured", 1, 2)
    assert acc["items"] == [{"id": pk, "name": "prod", "provider": "aws", "regions": 2, "check": None}]

    r = _test(env, h, pk, OK)
    assert r.status_code == 200 and r.json()["success"] is True and r.json()["name"] == "prod"      # as before
    acc = env.client.get(URL, headers=h).json()["accounts"]
    check = acc["items"][0]["check"]
    assert acc["state"] == "connected"
    assert (check["ok"], check["checked_by"], check["detail"]) == (True, "user:root@x", "")
    assert check["checked_at"].endswith("Z")


def test_a_failed_test_says_so_and_a_later_pass_takes_over(env):
    h = env.login("root@x", is_admin=True)
    pk = _account()
    _test(env, h, pk, _no("An error occurred (AccessDenied) when calling the AssumeRole operation: not authorized"))
    acc = env.client.get(URL, headers=h).json()["accounts"]
    assert acc["state"] == "failed" and acc["items"][0]["check"]["ok"] is False
    assert "AccessDenied" in acc["items"][0]["check"]["detail"]
    _test(env, h, pk, OK)
    assert env.client.get(URL, headers=h).json()["accounts"]["state"] == "connected"      # the newest check decides


def test_one_untested_or_one_failed_account_decides_for_all(env):
    h = env.login("root@x", is_admin=True)
    a, b = _account("a"), _account("b", role="arn:aws:iam::222222222222:role/ops")
    _test(env, h, a, OK)
    assert env.client.get(URL, headers=h).json()["accounts"]["state"] == "configured"     # b was never tested
    _test(env, h, b, _no("timeout"))
    assert env.client.get(URL, headers=h).json()["accounts"]["state"] == "failed"
    _test(env, h, b, OK)
    assert env.client.get(URL, headers=h).json()["accounts"]["state"] == "connected"


def test_a_check_counts_only_for_the_credentials_it_was_made_with(env):
    from agenticops.models import CloudAccount, get_db_session
    h = env.login("root@x", is_admin=True)
    pk = _account()
    _test(env, h, pk, OK)
    with get_db_session() as s:                                               # the account is pointed at another role
        s.get(CloudAccount, pk).credentials = {"role_arn": "arn:aws:iam::333333333333:role/other"}
    acc = env.client.get(URL, headers=h).json()["accounts"]
    assert (acc["state"], acc["items"][0]["check"]) == ("configured", None)


def test_what_is_kept_of_a_failure_is_short_and_carries_no_secret(env):
    h = env.login("root@x", is_admin=True)
    pk = _account()
    _test(env, h, pk, _no("key AKIAIOSFODNN7EXAMPLE was refused " + "x" * 900))
    detail = env.client.get(URL, headers=h).json()["accounts"]["items"][0]["check"]["detail"]
    assert "AKIAIOSFODNN7EXAMPLE" not in detail and len(detail) <= 500


def test_a_secret_is_masked_before_the_detail_is_cut(env):
    """Cut first and a key that straddles the limit is left as a piece no pattern recognises any more."""
    h = env.login("root@x", is_admin=True)
    pk = _account()
    _test(env, h, pk, _no("e" * 490 + " AKIAIOSFODNN7EXAMPLE was refused"))
    detail = env.client.get(URL, headers=h).json()["accounts"]["items"][0]["check"]["detail"]
    assert len(detail) == 500 and "AKIA" not in detail


def test_testing_an_unknown_account_is_404_and_leaves_no_record(env):
    from agenticops.models import ReadinessCheck, get_db_session
    h = env.login("root@x", is_admin=True)
    assert env.client.post("/api/accounts/999/test", headers=h).status_code == 404
    with get_db_session() as s:
        assert s.query(ReadinessCheck).count() == 0


# ── the main model: verified is a call that was made ──────────────────────────────────────────────────────────

def _verify(env, headers, side_effect=None, text="pong"):
    calls = []

    def fake(model_id, prompt, **kw):
        calls.append((model_id, kw))
        if side_effect is not None:
            raise side_effect
        return text, {"input": 8, "output": 2}, "end_turn"
    with patch("agenticops.agents.preamble.converse_text", side_effect=fake):
        return env.client.post("/api/setup/verify-model", headers=headers), calls


def test_an_admin_verifies_the_model_with_one_tiny_call(env):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    h = env.login("root@x", is_admin=True)
    r, calls = _verify(env, h)
    assert r.status_code == 200, r.text
    assert calls == [("global.anthropic.claude-opus-5-5", {"max_tokens": 16, "read_timeout": 60, "total_attempts": 1})]
    body = r.json()
    assert (body["ok"], body["checked_by"]) == (True, "user:root@x") and body["checked_at"].endswith("Z")
    model = env.client.get(URL, headers=h).json()["model"]
    assert model["state"] == "verified" and model["check"]["checked_at"] == body["checked_at"]
    with get_db_session() as s:
        rows = [(a.action, a.entity_type, a.entity_name, a.actor, a.new_values) for a in s.query(AuditLog).filter(AuditLog.entity_type == "readiness_check")]
    assert rows == [("verify_model", "readiness_check", "global.anthropic.claude-opus-5-5", "user:root@x", {"ok": True, "region": "us-east-1"})]


def test_a_reply_cut_at_the_limit_is_still_an_answer(env):
    """Sixteen tokens is all it may spend: a model that thinks first can stop there — it was reached and it answered."""
    from agenticops.agents.preamble import ModelReplyEmpty, ModelReplyTruncated
    h = env.login("root@x", is_admin=True)
    for reply in (ModelReplyTruncated("stopped at its 16-token output limit"), ModelReplyEmpty("returned no text")):
        r, _ = _verify(env, h, side_effect=reply)
        assert r.json()["ok"] is True, reply
    assert env.client.get(URL, headers=h).json()["model"]["state"] == "verified"


def test_a_refused_call_fails_the_verification_and_names_the_error_not_the_message(env):
    h = env.login("root@x", is_admin=True)
    refused = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "User arn:aws:iam::111111111111:user/x is not authorized"}}, "Converse")
    r, _ = _verify(env, h, side_effect=refused)
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["detail"] == "AccessDeniedException (Converse)"
    assert env.client.get(URL, headers=h).json()["model"]["state"] == "failed"


def test_a_verification_counts_only_for_the_model_and_region_it_was_made_with(env):
    h = env.login("root@x", is_admin=True)
    _verify(env, h)
    env.monkeypatch.setattr(env.settings, "agent_main_model_id", "global.anthropic.claude-fable-5-2")
    model = env.client.get(URL, headers=h).json()["model"]
    assert (model["state"], model["model_id"], model["check"]) == ("configured", "global.anthropic.claude-fable-5-2", None)
    env.monkeypatch.setattr(env.settings, "agent_main_model_id", "global.anthropic.claude-opus-5-5")
    env.monkeypatch.setattr(env.settings, "bedrock_region", "eu-west-1")
    assert env.client.get(URL, headers=h).json()["model"]["state"] == "configured"


def test_only_an_admin_verifies(env):
    writer = env.login("ops@x", permissions=["read", "write"])
    viewer = env.login("eyes@x", permissions=["read"])
    for headers in (writer, viewer):
        r, calls = _verify(env, headers)
        assert r.status_code == 403 and calls == []
    assert env.client.post("/api/setup/verify-model").status_code == 401


# ── execution and approval: who decides ───────────────────────────────────────────────────────────────────────

def test_execution_says_how_much_runs_without_a_person_and_what_you_may_do(env):
    admin = env.login("root@x", is_admin=True)
    ex = env.client.get(URL, headers=admin).json()["execution"]
    assert ex == {"state": "manual", "executor_enabled": False, "auto_fix_enabled": False, "auto_approve_l0_l1": False,
                  "rbac_enforce": False, "change_auto_approve_standard": False, "you_can_approve": True, "read_only": False}
    for flag in ("executor_enabled", "auto_fix_enabled"):
        env.monkeypatch.setattr(env.settings, flag, True)
    assert env.client.get(URL, headers=admin).json()["execution"]["state"] == "manual"         # a person still approves
    env.monkeypatch.setattr(env.settings, "executor_auto_approve_l0_l1", True)
    assert env.client.get(URL, headers=admin).json()["execution"]["state"] == "partly_automatic"
    # the state is about who APPROVES (pipeline_service.trigger_auto_approve reads auto_fix + auto-approve, not the
    # executor): with the executor off an L0 / L1 plan is still approved without a person — it just does not run
    env.monkeypatch.setattr(env.settings, "executor_enabled", False)
    assert env.client.get(URL, headers=admin).json()["execution"]["state"] == "partly_automatic"
    env.monkeypatch.setattr(env.settings, "auto_fix_enabled", False)
    assert env.client.get(URL, headers=admin).json()["execution"]["state"] == "manual"         # the pipeline approves nothing
    env.monkeypatch.setattr(env.settings, "change_auto_approve_standard", True)
    assert env.client.get(URL, headers=admin).json()["execution"]["state"] == "partly_automatic"


def test_a_read_only_account_sees_it_all_and_may_verify_nothing(env):
    _account()
    body = env.client.get(URL, headers=env.login("eyes@x", permissions=["read"])).json()
    assert body["can_verify"] is False
    assert (body["execution"]["state"], body["execution"]["read_only"], body["execution"]["you_can_approve"]) == ("read_only", True, False)
    assert body["accounts"]["state"] == "configured" and body["model"]["model_id"]
    writer = env.client.get(URL, headers=env.login("ops@x", permissions=["read", "write"])).json()
    assert (writer["can_verify"], writer["execution"]["read_only"], writer["execution"]["you_can_approve"]) == (False, False, True)


def test_the_handlers_are_plain_functions():
    from agenticops.web.routers import setup
    handlers = [r.endpoint for r in setup.router.routes]
    assert len(handlers) == 2 and not any(inspect.iscoroutinefunction(h) for h in handlers)
