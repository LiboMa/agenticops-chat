"""Tests for multi-cloud API endpoints (Chunk 5).

Tests /api/cloud/accounts and /api/cloud/resources endpoints.
"""

import json
import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import Base, CloudAccount, CloudResource


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Create a test FastAPI client with fresh DB."""
    db_path = tmp_path / "test_api.db"
    db_url = f"sqlite:///{db_path}"

    # Set up credential key
    monkeypatch.setenv("CLAWOPS_CREDENTIAL_KEY", Fernet.generate_key().decode())
    from agenticops.providers.credential_store import reset_credential_store
    reset_credential_store()

    engine = create_engine(db_url, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    from contextlib import contextmanager

    @contextmanager
    def mock_db_session():
        session = TestSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Patch get_db_session in models (api_cloud imports from there)
    monkeypatch.setattr("agenticops.models.get_db_session", mock_db_session)

    from agenticops.web.api_cloud import cloud_router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(cloud_router)
    client = TestClient(app)

    yield client, TestSession

    reset_credential_store()
    engine.dispose()


# ---------------------------------------------------------------------------
# Account CRUD tests
# ---------------------------------------------------------------------------


class TestCloudAccountAPI:
    """Tests for /api/cloud/accounts endpoints."""

    def test_create_account(self, test_client):
        client, _ = test_client
        resp = client.post("/api/cloud/accounts", json={
            "name": "prod-aws",
            "provider": "aws",
            "credentials": {"role_arn": "arn:aws:iam::123:role/Ops"},
            "regions": ["us-east-1"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "prod-aws"
        assert data["provider"] == "aws"
        assert data["has_credentials"] is True
        # Credentials must NOT appear in response
        assert "credentials" not in data or data.get("credentials") is None
        assert "role_arn" not in json.dumps(data)

    def test_list_accounts(self, test_client):
        client, _ = test_client
        client.post("/api/cloud/accounts", json={"name": "a1", "provider": "aws"})
        client.post("/api/cloud/accounts", json={"name": "a2", "provider": "azure"})
        resp = client.get("/api/cloud/accounts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_accounts_filter_provider(self, test_client):
        client, _ = test_client
        client.post("/api/cloud/accounts", json={"name": "a1", "provider": "aws"})
        client.post("/api/cloud/accounts", json={"name": "a2", "provider": "azure"})
        resp = client.get("/api/cloud/accounts?provider=aws")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["provider"] == "aws"

    def test_get_account(self, test_client):
        client, _ = test_client
        create_resp = client.post("/api/cloud/accounts", json={
            "name": "test-get", "provider": "gcp",
            "credentials": {"project_id": "proj-1"},
        })
        acct_id = create_resp.json()["id"]
        resp = client.get(f"/api/cloud/accounts/{acct_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-get"
        assert "project_id" not in json.dumps(resp.json())

    def test_get_account_not_found(self, test_client):
        client, _ = test_client
        resp = client.get("/api/cloud/accounts/999")
        assert resp.status_code == 404

    def test_update_account(self, test_client):
        client, _ = test_client
        create_resp = client.post("/api/cloud/accounts", json={
            "name": "update-me", "provider": "aws",
        })
        acct_id = create_resp.json()["id"]
        resp = client.put(f"/api/cloud/accounts/{acct_id}", json={
            "regions": ["eu-west-1", "us-east-1"],
            "is_enabled": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["regions"] == ["eu-west-1", "us-east-1"]
        assert data["is_enabled"] is False

    def test_delete_account(self, test_client):
        client, _ = test_client
        create_resp = client.post("/api/cloud/accounts", json={
            "name": "delete-me", "provider": "aws",
        })
        acct_id = create_resp.json()["id"]
        resp = client.delete(f"/api/cloud/accounts/{acct_id}")
        assert resp.status_code == 204
        # Verify deleted
        resp = client.get(f"/api/cloud/accounts/{acct_id}")
        assert resp.status_code == 404

    def test_duplicate_name_rejected(self, test_client):
        client, _ = test_client
        client.post("/api/cloud/accounts", json={"name": "dup", "provider": "aws"})
        resp = client.post("/api/cloud/accounts", json={"name": "dup", "provider": "azure"})
        assert resp.status_code == 400

    def test_invalid_provider_rejected(self, test_client):
        client, _ = test_client
        resp = client.post("/api/cloud/accounts", json={
            "name": "bad-provider", "provider": "digitalocean",
        })
        assert resp.status_code == 422  # Pydantic validation

    def test_credentials_never_in_response(self, test_client):
        """Verify credentials are NEVER exposed in any API response."""
        client, _ = test_client
        create_resp = client.post("/api/cloud/accounts", json={
            "name": "secret-test", "provider": "aws",
            "credentials": {"secret_key": "super-secret-value"},
        })
        assert create_resp.status_code == 201
        assert "super-secret-value" not in create_resp.text
        assert "secret_key" not in create_resp.text

        # Also check GET
        acct_id = create_resp.json()["id"]
        get_resp = client.get(f"/api/cloud/accounts/{acct_id}")
        assert "super-secret-value" not in get_resp.text

        # And LIST
        list_resp = client.get("/api/cloud/accounts")
        assert "super-secret-value" not in list_resp.text


# ---------------------------------------------------------------------------
# Resource listing tests
# ---------------------------------------------------------------------------


class TestCloudResourceAPI:
    """Tests for /api/cloud/resources endpoint."""

    def test_list_resources_empty(self, test_client):
        client, _ = test_client
        resp = client.get("/api/cloud/resources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_resources_with_data(self, test_client):
        client, Session = test_client
        # Create account + resource directly in DB
        session = Session()
        acct = CloudAccount(name="res-test", provider="aws", is_enabled=True)
        acct.credentials = {"role_arn": "test"}
        session.add(acct)
        session.flush()
        resource = CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="EC2", resource_id="i-test", name="web",
            status="active", managed=True,
        )
        session.add(resource)
        session.commit()
        session.close()

        resp = client.get("/api/cloud/resources")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["resource_id"] == "i-test"

    def test_filter_resources_by_provider(self, test_client):
        client, Session = test_client
        session = Session()
        acct = CloudAccount(name="filter-test", provider="aws", is_enabled=True)
        session.add(acct)
        session.flush()
        session.add(CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="EC2", resource_id="i-1", status="active",
        ))
        session.commit()
        session.close()

        resp = client.get("/api/cloud/resources?provider=azure")
        assert resp.status_code == 200
        assert resp.json() == []

        resp = client.get("/api/cloud/resources?provider=aws")
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Validate endpoint tests
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    """Tests for /api/cloud/accounts/{id}/validate."""

    def test_validate_no_credentials(self, test_client):
        client, _ = test_client
        create_resp = client.post("/api/cloud/accounts", json={
            "name": "no-creds", "provider": "aws",
        })
        acct_id = create_resp.json()["id"]
        resp = client.post(f"/api/cloud/accounts/{acct_id}/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "No credentials" in data["message"]

    def test_validate_not_found(self, test_client):
        client, _ = test_client
        resp = client.post("/api/cloud/accounts/999/validate")
        assert resp.status_code == 404
