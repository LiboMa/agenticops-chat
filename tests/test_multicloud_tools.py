"""Tests for multi-cloud metadata tools (Chunk 4).

Tests the new get_enabled_accounts, get_cloud_resources, and upsert_cloud_resource
tools that work with CloudAccount/CloudResource models.
"""

import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import Base, CloudAccount, CloudResource, init_db


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """Create a fresh in-memory DB with CloudAccount/CloudResource tables."""
    db_path = tmp_path / "test_tools.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Patch get_session to return our test session
    monkeypatch.setattr("agenticops.tools.metadata_tools.get_session", lambda: session)

    # Set up credential key for CloudAccount
    from cryptography.fernet import Fernet
    monkeypatch.setenv("CLAWOPS_CREDENTIAL_KEY", Fernet.generate_key().decode())
    from agenticops.providers.credential_store import reset_credential_store
    reset_credential_store()

    yield session

    reset_credential_store()
    session.close()
    engine.dispose()


@pytest.fixture
def sample_accounts(db_session):
    """Create sample CloudAccounts for testing."""
    aws = CloudAccount(name="prod-aws", provider="aws", is_enabled=True, regions=["us-east-1", "eu-west-1"])
    aws.credentials = {"role_arn": "arn:aws:iam::123:role/Ops"}
    azure = CloudAccount(name="prod-azure", provider="azure", is_enabled=True, regions=["eastus"])
    azure.credentials = {"subscription_id": "sub-123", "tenant_id": "t-1"}
    disabled = CloudAccount(name="old-gcp", provider="gcp", is_enabled=False, regions=["us-central1"])
    disabled.credentials = {"project_id": "old-proj"}

    db_session.add_all([aws, azure, disabled])
    db_session.commit()
    return {"aws": aws, "azure": azure, "disabled": disabled}


@pytest.fixture
def sample_resources(db_session, sample_accounts):
    """Create sample CloudResources for testing."""
    r1 = CloudResource(
        account_id=sample_accounts["aws"].id, provider="aws", region="us-east-1",
        resource_type="EC2", resource_id="i-abc123", name="web-1",
        status="active", tags={"env": "prod"}, managed=True,
    )
    r2 = CloudResource(
        account_id=sample_accounts["aws"].id, provider="aws", region="eu-west-1",
        resource_type="RDS", resource_id="db-xyz", name="main-db",
        status="active", tags={"env": "prod"}, managed=True,
    )
    r3 = CloudResource(
        account_id=sample_accounts["azure"].id, provider="azure", region="eastus",
        resource_type="VM", resource_id="vm-001", name="api-server",
        status="active", tags={}, managed=True,
    )
    db_session.add_all([r1, r2, r3])
    db_session.commit()
    return [r1, r2, r3]


# ---------------------------------------------------------------------------
# get_enabled_accounts tests
# ---------------------------------------------------------------------------


class TestGetEnabledAccounts:
    """Tests for get_enabled_accounts tool."""

    def test_returns_all_enabled(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        result = json.loads(get_enabled_accounts())
        assert len(result) == 2  # aws + azure, not disabled gcp
        providers = {a["provider"] for a in result}
        assert providers == {"aws", "azure"}

    def test_filter_by_provider(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        result = json.loads(get_enabled_accounts(provider="aws"))
        assert len(result) == 1
        assert result[0]["name"] == "prod-aws"

    def test_no_credentials_in_output(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        result_str = get_enabled_accounts()
        assert "role_arn" not in result_str
        assert "subscription_id" not in result_str
        assert "credentials" not in result_str

    def test_empty_result(self, db_session):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        result = get_enabled_accounts()
        assert "No enabled cloud accounts" in result

    def test_disabled_not_returned(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import get_enabled_accounts
        result = json.loads(get_enabled_accounts())
        names = {a["name"] for a in result}
        assert "old-gcp" not in names


# ---------------------------------------------------------------------------
# get_cloud_resources tests
# ---------------------------------------------------------------------------


class TestGetCloudResources:
    """Tests for get_cloud_resources tool."""

    def test_returns_all(self, db_session, sample_resources):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources())
        assert len(result) == 3

    def test_filter_by_provider(self, db_session, sample_resources):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources(provider="azure"))
        assert len(result) == 1
        assert result[0]["provider"] == "azure"

    def test_filter_by_resource_type(self, db_session, sample_resources):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources(resource_type="EC2"))
        assert len(result) == 1
        assert result[0]["resource_id"] == "i-abc123"

    def test_filter_by_region(self, db_session, sample_resources):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources(region="eu-west-1"))
        assert len(result) == 1
        assert result[0]["name"] == "main-db"

    def test_filter_by_account_id(self, db_session, sample_resources, sample_accounts):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources(account_id=sample_accounts["azure"].id))
        assert len(result) == 1
        assert result[0]["provider"] == "azure"

    def test_empty_result(self, db_session):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = get_cloud_resources()
        assert "No cloud resources found" in result

    def test_combined_filters(self, db_session, sample_resources):
        from agenticops.tools.metadata_tools import get_cloud_resources
        result = json.loads(get_cloud_resources(provider="aws", region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_type"] == "EC2"


# ---------------------------------------------------------------------------
# upsert_cloud_resource tests
# ---------------------------------------------------------------------------


class TestUpsertCloudResource:
    """Tests for upsert_cloud_resource tool."""

    def test_create_resource(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import upsert_cloud_resource
        result = json.loads(upsert_cloud_resource(
            account_id=sample_accounts["aws"].id,
            provider="aws",
            region="us-east-1",
            resource_type="Lambda",
            resource_id="fn-new-123",
            name="my-function",
            status="active",
        ))
        assert result["action"] == "created"
        assert result["resource_id"] == "fn-new-123"

        # Verify in DB
        resource = db_session.query(CloudResource).filter_by(resource_id="fn-new-123").first()
        assert resource is not None
        assert resource.name == "my-function"
        assert resource.provider == "aws"

    def test_update_existing_resource(self, db_session, sample_accounts, sample_resources):
        from agenticops.tools.metadata_tools import upsert_cloud_resource
        result = json.loads(upsert_cloud_resource(
            account_id=sample_accounts["aws"].id,
            provider="aws",
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-abc123",
            name="web-1-updated",
            status="stopped",
        ))
        assert result["action"] == "updated"

        # Verify update
        resource = db_session.query(CloudResource).filter_by(resource_id="i-abc123").first()
        assert resource.name == "web-1-updated"
        assert resource.status == "stopped"
        assert resource.scanned_at is not None

    def test_upsert_with_tags_json(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import upsert_cloud_resource
        tags = json.dumps({"env": "staging", "team": "ops"})
        result = json.loads(upsert_cloud_resource(
            account_id=sample_accounts["aws"].id,
            provider="aws",
            region="us-west-2",
            resource_type="S3",
            resource_id="my-bucket",
            tags=tags,
        ))
        assert result["action"] == "created"

        resource = db_session.query(CloudResource).filter_by(resource_id="my-bucket").first()
        assert resource.tags == {"env": "staging", "team": "ops"}

    def test_provider_normalized_to_lowercase(self, db_session, sample_accounts):
        from agenticops.tools.metadata_tools import upsert_cloud_resource
        result = json.loads(upsert_cloud_resource(
            account_id=sample_accounts["aws"].id,
            provider="AWS",  # uppercase
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-upper-test",
        ))
        assert result["action"] == "created"
        resource = db_session.query(CloudResource).filter_by(resource_id="i-upper-test").first()
        assert resource.provider == "aws"  # lowercase
