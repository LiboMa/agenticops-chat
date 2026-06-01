import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from fastapi.testclient import TestClient

from agenticops.models import init_db, CloudAccount, get_db_session
from agenticops.web.app import app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)
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
    assert len(resp.json()) == 1
    assert resp.json()[0]["provider"] == "aws"


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
    # Test endpoint — will attempt to resolve credentials
    with patch("agenticops.providers.get_provider") as mock_gp:
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_gp.return_value = mock_provider
        resp = client.post(f"/api/accounts/{account_id}/test")
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
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
