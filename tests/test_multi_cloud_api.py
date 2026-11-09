import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from fastapi.testclient import TestClient

from agenticops.models import init_db, CloudAccount, get_db_session
from agenticops.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
    # The account routes live in web/routers/accounts and open their own sessions: the process-wide engine must be this
    # test's database too, never the one AIOPS_DATABASE_URL names (2026-11-08: rows piled up there across runs → 409)
    import agenticops.models as models_mod
    from agenticops.config import settings as real_settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(real_settings, "database_url", f"sqlite:///{db_path}")
    # Patch get_db_session to use test engine
    from agenticops.models import Base
    from sqlalchemy.orm import Session
    from contextlib import contextmanager

    @contextmanager
    def test_db_session():
        session = Session(bind=engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with patch("agenticops.web.app.get_db_session", test_db_session), \
         patch("agenticops.web.app.init_db"), \
         patch("agenticops.web.app._chat_sessions"), \
         patch("agenticops.web.app._executor_service"), \
         patch("agenticops.scheduler.scheduler.Scheduler.start"), \
         patch("agenticops.scheduler.scheduler.Scheduler.stop"), \
         patch("agenticops.notify.im_config.load_channels", return_value=[]), \
         patch("agenticops.web.app.settings") as mock_settings:
        mock_settings.feishu_ws_enabled = False
        mock_settings.slack_ws_enabled = False
        mock_settings.executor_poll_interval = 60
        mock_settings.event_loop_executor_threads = 8
        mock_settings.data_dir = tmp_path  # the instance lock file; a MagicMock path wrote MagicMock/ in the repo
        mock_settings.log_dir = tmp_path / "logs"  # the lifespan's log handlers — never the running service's logs/
        with TestClient(app) as c:
            yield c


def test_create_account_aws(client):
    resp = client.post("/api/accounts", json={
        "name": "aws-prod",
        "provider": "aws",
        "credentials": {"role_arn": "arn:aws:iam::123456789012:role/ops", "account_id": "123456789012"},
        "regions": ["us-east-1"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "aws"
    assert data["is_enabled"] is True


def test_create_account_azure(client):
    resp = client.post("/api/accounts", json={
        "name": "azure-prod",
        "provider": "azure",
        "credentials": {"subscription_id": "sub-xxx", "tenant_id": "t-xxx"},
        "regions": ["eastus"],
    })
    assert resp.status_code == 201
    assert resp.json()["provider"] == "azure"


def test_list_accounts_filter_by_provider(client):
    client.post("/api/accounts", json={"name": "a1", "provider": "aws", "credentials": {}, "regions": []})
    client.post("/api/accounts", json={"name": "a2", "provider": "azure", "credentials": {}, "regions": []})
    resp = client.get("/api/accounts?provider=aws")
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) >= 1
    assert all(a["provider"] == "aws" for a in accounts)
    # Ensure our azure account is NOT in the filtered list
    assert not any(a["name"] == "a2" for a in accounts)


def test_create_account_duplicate_name(client):
    client.post("/api/accounts", json={"name": "dup", "provider": "aws", "credentials": {}, "regions": []})
    resp = client.post("/api/accounts", json={"name": "dup", "provider": "azure", "credentials": {}, "regions": []})
    assert resp.status_code == 409


def test_test_account_connection(client):
    resp = client.post("/api/accounts", json={
        "name": "test-aws", "provider": "aws",
        "credentials": {"profile_name": "default"}, "regions": ["us-east-1"],
    })
    account_id = resp.json()["id"]
    # The endpoint goes through SessionFactory.test_connection: stub the session it builds, so the STS
    # GetCallerIdentity never leaves the machine.
    session = MagicMock()
    session.client.return_value.get_caller_identity.return_value = {
        "Arn": "arn:aws:iam::111111111111:user/t", "Account": "111111111111"}
    with patch("agenticops.credentials.session_factory.SessionFactory.get_session", return_value=session):
        resp = client.post(f"/api/accounts/{account_id}/test")
    assert resp.status_code == 200
    data = resp.json()
    assert (data["success"], data["account_id"]) == (True, "111111111111")
    assert data["provider"] == "aws"


def test_test_account_not_found(client):
    resp = client.post("/api/accounts/99999/test")
    assert resp.status_code == 404


def test_account_response_redacts_secrets(client):
    resp = client.post("/api/accounts", json={
        "name": "secret-test", "provider": "azure",
        "credentials": {"client_secret": "super-secret", "tenant_id": "t-xxx"},
        "regions": ["eastus"],
    })
    assert resp.status_code == 201
    data = resp.json()
    # client_secret should be redacted in response
    assert data["credentials"].get("client_secret") != "super-secret"


def test_get_account(client):
    resp = client.post("/api/accounts", json={
        "name": "get-test", "provider": "gcp",
        "credentials": {"project_id": "my-proj"}, "regions": ["us-central1"],
    })
    account_id = resp.json()["id"]
    resp = client.get(f"/api/accounts/{account_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "get-test"
    assert resp.json()["provider"] == "gcp"


def test_update_account(client):
    resp = client.post("/api/accounts", json={
        "name": "upd-test", "provider": "aws", "credentials": {}, "regions": ["us-east-1"],
    })
    account_id = resp.json()["id"]
    resp = client.put(f"/api/accounts/{account_id}", json={"is_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False


def test_delete_account(client):
    resp = client.post("/api/accounts", json={
        "name": "del-test", "provider": "aws", "credentials": {}, "regions": [],
    })
    account_id = resp.json()["id"]
    resp = client.delete(f"/api/accounts/{account_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/accounts/{account_id}")
    assert resp.status_code == 404


# ── An edit keeps what the form cannot see; account changes are audited (2026-11-09) ──

import json

ROLE = "arn:aws:iam::111122223333:role/AgenticOpsRole"
AK, SK = "AKIAEXAMPLEOLD12345", "old-secret-access-key-value"


@pytest.fixture
def store(monkeypatch):
    from agenticops.credentials import store as store_mod
    s = store_mod.CredentialStore(store_mod.LocalKeyBackend("account-api-test-key"))
    monkeypatch.setattr(store_mod, "_store_instance", s)
    return s


def _row(account_id):
    with get_db_session() as db:
        a = db.query(CloudAccount).filter_by(id=account_id).one()
        return dict(a.credentials or {}), list(a.regions or []), a.credential_source_type


def _audit_rows(account_id):
    from agenticops.audit.models import AuditLog
    with get_db_session() as db:
        rows = (db.query(AuditLog).filter_by(entity_type="account", entity_id=str(account_id))
                .order_by(AuditLog.id).all())
        return [{"action": r.action, "actor": r.actor, "user_id": r.user_id, "name": r.entity_name,
                 "details": r.details, "old": r.old_values, "new": r.new_values} for r in rows]


def _create_global(client):
    resp = client.post("/api/accounts", json={
        "name": "global", "provider": "aws", "credential_source_type": "assume_role",
        "credentials": {"role_arn": ROLE, "external_id": "ext-1", "account_id": "111122223333",
                        "access_key_id": AK, "secret_access_key": SK},
        "regions": ["us-east-1"], "is_enabled": False})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_a_region_edit_keeps_the_stored_keys(client, store):
    # exactly the body the Settings form sent on 2026-11-09: the form never sees the stored keys
    aid = _create_global(client)
    resp = client.put(f"/api/accounts/{aid}", json={
        "name": "global", "credential_source_type": "assume_role",
        "credentials": {"role_arn": ROLE, "external_id": "ext-1"},
        "regions": ["us-east-1", "eu-west-1"], "is_enabled": False})
    assert resp.status_code == 200
    creds, regions, _ = _row(aid)
    assert "_encrypted" in creds
    plain = store.decrypt_credentials(creds)
    assert (plain["access_key_id"], plain["secret_access_key"]) == (AK, SK)
    assert plain["account_id"] == "111122223333"  # no input for it in assume_role mode: kept
    assert regions == ["us-east-1", "eu-west-1"]


def test_an_empty_or_null_credentials_body_changes_nothing(client, store):
    aid = _create_global(client)
    before = store.decrypt_credentials(_row(aid)[0])
    for body in ({"credentials": {}}, {"credentials": None}):
        assert client.put(f"/api/accounts/{aid}", json=body).status_code == 200
        assert store.decrypt_credentials(_row(aid)[0]) == before


def test_the_redacted_response_sent_back_changes_nothing(client, store):
    aid = _create_global(client)
    shown = client.get(f"/api/accounts/{aid}").json()
    assert shown["credentials"]["_encrypted"] == "***REDACTED***"
    assert client.put(f"/api/accounts/{aid}", json={"credentials": shown["credentials"]}).status_code == 200
    plain = store.decrypt_credentials(_row(aid)[0])
    assert (plain["access_key_id"], plain["secret_access_key"]) == (AK, SK)


def test_a_new_secret_replaces_only_itself(client, store):
    aid = _create_global(client)
    assert client.put(f"/api/accounts/{aid}", json={"credentials": {"secret_access_key": "new-secret"}}).status_code == 200
    plain = store.decrypt_credentials(_row(aid)[0])
    assert (plain["access_key_id"], plain["secret_access_key"]) == (AK, "new-secret")


def test_clear_secrets_removes_the_stored_keys(client, store):
    aid = _create_global(client)
    resp = client.put(f"/api/accounts/{aid}", json={"clear_secrets": True})
    assert resp.status_code == 200
    assert _row(aid)[0] == {"role_arn": ROLE, "external_id": "ext-1", "account_id": "111122223333"}
    assert "***REDACTED***" not in resp.text


def test_switching_to_access_keys_drops_the_role(client, store):
    aid = _create_global(client)
    assert client.put(f"/api/accounts/{aid}", json={
        "credential_source_type": "static_keys",
        "credentials": {"access_key_id": "AKIANEW", "secret_access_key": "new", "account_id": "111122223333"},
    }).status_code == 200
    creds, _, source = _row(aid)
    plain = store.decrypt_credentials(creds)
    assert source == "static_keys"
    assert "role_arn" not in plain and "external_id" not in plain
    assert (plain["access_key_id"], plain["secret_access_key"]) == ("AKIANEW", "new")


def test_the_update_response_still_redacts(client, store):
    aid = _create_global(client)
    resp = client.put(f"/api/accounts/{aid}", json={"regions": ["us-west-2"]})
    assert AK not in resp.text and SK not in resp.text
    assert resp.json()["credentials"]["_encrypted"] == "***REDACTED***"


def test_create_update_delete_are_audited_without_a_secret(client, store):
    aid = _create_global(client)
    blob = _row(aid)[0]["_encrypted"]
    client.put(f"/api/accounts/{aid}", json={"credentials": {"role_arn": ROLE}, "regions": ["us-east-1", "eu-west-1"]})
    client.put(f"/api/accounts/{aid}", json={"credentials": {"secret_access_key": "new-secret"}})
    client.put(f"/api/accounts/{aid}", json={"clear_secrets": True})
    assert client.delete(f"/api/accounts/{aid}").status_code == 204

    rows = _audit_rows(aid)
    assert [r["action"] for r in rows] == ["create", "update", "update", "update", "delete"]
    assert {r["actor"] for r in rows} == {"web:anonymous"}
    assert {r["name"] for r in rows} == {"global"}
    assert [r["details"].get("secrets") for r in rows] == ["added", "kept", "replaced", "removed", None]
    assert {r["details"]["via"] for r in rows} == {"web"}
    created, regions_edit, _, cleared, deleted = rows
    assert created["new"]["credentials"] == {"role_arn": ROLE, "external_id": "ext-1", "account_id": "111122223333"}
    assert created["new"]["stored_secrets"] is True
    assert (regions_edit["old"]["regions"], regions_edit["new"]["regions"]) == (["us-east-1"], ["us-east-1", "eu-west-1"])
    assert (cleared["old"]["stored_secrets"], cleared["new"]["stored_secrets"]) == (True, False)
    assert deleted["old"]["name"] == "global" and deleted["new"] is None
    text = json.dumps(rows)
    for secret in (AK, SK, "new-secret", blob):
        assert secret not in text


def test_a_refused_delete_writes_no_audit_row(client, store):
    aid = _create_global(client)
    from sqlalchemy.exc import IntegrityError
    with patch("sqlalchemy.orm.Session.delete", side_effect=IntegrityError("DELETE", {}, Exception("fk"))):
        assert client.delete(f"/api/accounts/{aid}").status_code == 409
    assert [r["action"] for r in _audit_rows(aid)] == ["create"]


def test_the_audit_rows_name_the_signed_in_user(client, store):
    # with api_auth_enabled the session's user is the actor (web/deps.current_actor), never the request body
    from agenticops.auth.actor import Actor
    from agenticops.web import deps
    from agenticops.web.app import app
    app.dependency_overrides[deps.current_actor] = lambda: Actor("user", "alice@example.com", 7, ("read", "write"))
    try:
        aid = _create_global(client)
        client.put(f"/api/accounts/{aid}", json={"regions": ["us-west-2"]})
        client.delete(f"/api/accounts/{aid}")
    finally:
        app.dependency_overrides.pop(deps.current_actor, None)
    assert {(r["actor"], r["user_id"]) for r in _audit_rows(aid)} == {("user:alice@example.com", 7)}
