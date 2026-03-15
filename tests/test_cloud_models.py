"""Tests for CloudAccount and CloudResource models."""

import json
import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from agenticops.models import (
    AWSAccount,
    Base,
    CloudAccount,
    CloudResource,
    HealthIssue,
    MonitoringConfig,
    get_session,
    init_db,
)
from agenticops.providers.credential_store import reset_credential_store


@pytest.fixture(autouse=True)
def _reset_cred_store():
    """Reset credential store singleton between tests."""
    reset_credential_store()
    yield
    reset_credential_store()


@pytest.fixture
def _fernet_key():
    """Provide a stable Fernet key via env var."""
    key = Fernet.generate_key().decode("ascii")
    with patch.dict(os.environ, {"CLAWOPS_CREDENTIAL_KEY": key}):
        yield key


@pytest.fixture
def db_session(tmp_path, _fernet_key):
    """Create a temporary database with all tables."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/test.db"

    engine = init_db()
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


class TestCloudAccountCreate:
    """Basic CRUD for CloudAccount."""

    def test_cloud_account_create(self, db_session):
        account = CloudAccount(
            name="my-aws-prod",
            provider="aws",
            regions=["us-east-1", "eu-west-1"],
            labels={"env": "prod"},
        )
        account.credentials = {"role_arn": "arn:aws:iam::123456789012:role/Ops"}
        db_session.add(account)
        db_session.commit()

        assert account.id is not None
        assert account.name == "my-aws-prod"
        assert account.provider == "aws"
        assert account.is_enabled is True
        assert account.regions == ["us-east-1", "eu-west-1"]
        assert account.labels == {"env": "prod"}
        assert account.created_at is not None


class TestCloudAccountCredentialsEncrypted:
    """Verify credentials_encrypted column is not plaintext."""

    def test_cloud_account_credentials_encrypted(self, db_session):
        creds = {
            "role_arn": "arn:aws:iam::123456789012:role/Ops",
            "external_id": "super-secret-ext-id",
        }
        account = CloudAccount(name="enc-test", provider="aws")
        account.credentials = creds
        db_session.add(account)
        db_session.commit()

        # Read raw encrypted column
        raw = account.credentials_encrypted
        assert raw is not None
        assert "super-secret-ext-id" not in raw
        assert "role_arn" not in raw
        assert raw != json.dumps(creds)


class TestCloudAccountCredentialsProperty:
    """Verify encrypt/decrypt roundtrip via property."""

    def test_cloud_account_credentials_property(self, db_session):
        creds = {
            "client_id": "app-xxx",
            "client_secret": "very-secret",
            "tenant_id": "t-123",
        }
        account = CloudAccount(name="azure-test", provider="azure")
        account.credentials = creds
        db_session.add(account)
        db_session.commit()

        # Re-query from DB
        db_session.expire(account)
        fetched = db_session.get(CloudAccount, account.id)
        assert fetched.credentials == creds

    def test_credentials_none_roundtrip(self, db_session):
        account = CloudAccount(name="no-creds", provider="gcp")
        account.credentials = None
        db_session.add(account)
        db_session.commit()

        assert account.credentials_encrypted is None
        assert account.credentials is None


class TestCloudAccountMultipleProviders:
    """Multiple enabled accounts across providers."""

    def test_cloud_account_multiple_providers(self, db_session):
        for provider, name in [
            ("aws", "aws-prod"),
            ("azure", "azure-prod"),
            ("gcp", "gcp-prod"),
            ("alicloud", "ali-prod"),
        ]:
            acc = CloudAccount(name=name, provider=provider, is_enabled=True)
            db_session.add(acc)
        db_session.commit()

        all_accounts = db_session.query(CloudAccount).filter_by(is_enabled=True).all()
        assert len(all_accounts) == 4
        providers = {a.provider for a in all_accounts}
        assert providers == {"aws", "azure", "gcp", "alicloud"}


class TestCloudAccountUniqueName:
    """Account names must be unique."""

    def test_cloud_account_unique_name(self, db_session):
        db_session.add(CloudAccount(name="dup-name", provider="aws"))
        db_session.commit()

        db_session.add(CloudAccount(name="dup-name", provider="gcp"))
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestCloudResourceCreate:
    """Basic CRUD for CloudResource with FK."""

    def test_cloud_resource_create(self, db_session):
        account = CloudAccount(name="res-test", provider="aws")
        db_session.add(account)
        db_session.commit()

        resource = CloudResource(
            account_id=account.id,
            provider="aws",
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-0123456789abcdef0",
            name="web-server-1",
            tags={"Name": "web-server-1"},
            raw_data={"InstanceType": "t3.medium"},
            status="running",
        )
        db_session.add(resource)
        db_session.commit()

        assert resource.id is not None
        assert resource.account_id == account.id
        assert resource.managed is True
        assert resource.account.name == "res-test"

        # Verify relationship from account side
        db_session.expire(account)
        assert len(account.resources) == 1


class TestCloudResourceUniqueConstraint:
    """Unique constraint on (account_id, provider, resource_id)."""

    def test_cloud_resource_unique_constraint(self, db_session):
        account = CloudAccount(name="uniq-res-test", provider="aws")
        db_session.add(account)
        db_session.commit()

        r1 = CloudResource(
            account_id=account.id,
            provider="aws",
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-duplicate",
        )
        db_session.add(r1)
        db_session.commit()

        r2 = CloudResource(
            account_id=account.id,
            provider="aws",
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-duplicate",
        )
        db_session.add(r2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestMigrationFromAWSAccount:
    """AWSAccount data migrates to CloudAccount with encrypted credentials."""

    def test_migration_from_aws_account(self, tmp_path, _fernet_key):
        """Old AWSAccount rows are migrated to cloud_accounts on init_db()."""
        import agenticops.models as models_mod
        from agenticops.config import settings
        from agenticops.providers.credential_store import get_credential_store

        models_mod._engine = None
        db_path = tmp_path / "migrate.db"
        settings.database_url = f"sqlite:///{db_path}"

        # Step 1: Create old-style DB with only aws_accounts
        engine = models_mod.get_engine()
        Base.metadata.create_all(engine)

        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO aws_accounts (name, account_id, role_arn, external_id, regions, is_active, created_at) "
                "VALUES ('prod', '123456789012', 'arn:aws:iam::123456789012:role/Ops', 'ext-123', "
                "'[\"us-east-1\"]', 1, '2026-01-01 00:00:00')"
            ))
            conn.commit()

        # Step 2: Drop cloud_accounts so init_db sees it as missing and triggers migration
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS cloud_resources"))
            conn.execute(text("DROP TABLE IF EXISTS cloud_accounts"))
            conn.commit()

        models_mod._engine = None
        reset_credential_store()

        # Step 3: Re-init — should create cloud_accounts and migrate
        engine = init_db()

        session = get_session()
        try:
            migrated = session.query(CloudAccount).filter_by(name="prod").first()
            assert migrated is not None
            assert migrated.provider == "aws"
            assert migrated.is_enabled is True

            # Verify credentials are encrypted and decryptable
            assert migrated.credentials_encrypted is not None
            creds = migrated.credentials
            assert creds["account_id"] == "123456789012"
            assert creds["role_arn"] == "arn:aws:iam::123456789012:role/Ops"
            assert creds["external_id"] == "ext-123"
        finally:
            session.close()
            models_mod._engine = None


class TestHealthIssueAccountId:
    """HealthIssue has optional account_id FK."""

    def test_health_issue_account_id(self, db_session):
        account = CloudAccount(name="hi-test", provider="aws")
        db_session.add(account)
        db_session.commit()

        issue = HealthIssue(
            resource_id="i-123",
            account_id=account.id,
            severity="high",
            source="manual",
            title="Test issue",
            description="test",
        )
        db_session.add(issue)
        db_session.commit()

        assert issue.account_id == account.id

    def test_health_issue_account_id_nullable(self, db_session):
        issue = HealthIssue(
            resource_id="i-456",
            severity="low",
            source="manual",
            title="No account",
            description="test",
        )
        db_session.add(issue)
        db_session.commit()

        assert issue.account_id is None
