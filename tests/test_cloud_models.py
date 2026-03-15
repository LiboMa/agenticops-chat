"""Tests for CloudAccount and CloudResource models."""

import pytest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from agenticops.models import (
    Base,
    CloudAccount,
    CloudResource,
    init_db,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database, run init_db, yield a session."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


class TestCloudAccount:
    """Tests for CloudAccount model."""

    def test_cloud_account_create(self, db_session: Session):
        """Create CloudAccount with all fields, verify persistence."""
        acct = CloudAccount(
            name="my-aws-prod",
            provider="aws",
            is_enabled=True,
            credentials={"role_arn": "arn:aws:iam::123456789012:role/Ops"},
            regions=["us-east-1", "eu-west-1"],
            labels={"env": "prod", "team": "platform"},
        )
        db_session.add(acct)
        db_session.commit()

        fetched = db_session.get(CloudAccount, acct.id)
        assert fetched is not None
        assert fetched.name == "my-aws-prod"
        assert fetched.provider == "aws"
        assert fetched.is_enabled is True
        assert fetched.credentials == {"role_arn": "arn:aws:iam::123456789012:role/Ops"}
        assert fetched.regions == ["us-east-1", "eu-west-1"]
        assert fetched.labels == {"env": "prod", "team": "platform"}
        assert isinstance(fetched.created_at, datetime)
        assert fetched.last_scanned_at is None

    def test_cloud_account_multiple_enabled(self, db_session: Session):
        """Two accounts can both be is_enabled=True simultaneously."""
        a1 = CloudAccount(name="aws-prod", provider="aws", is_enabled=True)
        a2 = CloudAccount(name="gcp-staging", provider="gcp", is_enabled=True)
        db_session.add_all([a1, a2])
        db_session.commit()

        enabled = db_session.query(CloudAccount).filter_by(is_enabled=True).all()
        assert len(enabled) == 2

    def test_cloud_account_unique_name(self, db_session: Session):
        """Duplicate name raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        a1 = CloudAccount(name="dup-name", provider="aws")
        db_session.add(a1)
        db_session.commit()

        a2 = CloudAccount(name="dup-name", provider="gcp")
        db_session.add(a2)
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestCloudResource:
    """Tests for CloudResource model."""

    def test_cloud_resource_create(self, db_session: Session):
        """Create CloudResource with FK to CloudAccount, verify relationship."""
        acct = CloudAccount(name="aws-test", provider="aws")
        db_session.add(acct)
        db_session.commit()

        res = CloudResource(
            account_id=acct.id,
            provider="aws",
            region="us-east-1",
            resource_type="EC2",
            resource_id="i-0abc123def456",
            name="web-server-1",
            tags={"env": "test"},
            raw_data={"instance_type": "t3.micro"},
            status="running",
            managed=True,
        )
        db_session.add(res)
        db_session.commit()

        fetched = db_session.get(CloudResource, res.id)
        assert fetched is not None
        assert fetched.account_id == acct.id
        assert fetched.provider == "aws"
        assert fetched.region == "us-east-1"
        assert fetched.resource_type == "EC2"
        assert fetched.resource_id == "i-0abc123def456"
        assert fetched.name == "web-server-1"
        assert fetched.tags == {"env": "test"}
        assert fetched.raw_data == {"instance_type": "t3.micro"}
        assert fetched.status == "running"
        assert fetched.managed is True
        assert isinstance(fetched.created_at, datetime)

        # Verify relationship
        assert fetched.account.name == "aws-test"
        assert len(acct.resources) == 1
        assert acct.resources[0].resource_id == "i-0abc123def456"

    def test_cloud_resource_unique_constraint(self, db_session: Session):
        """Duplicate (account_id, provider, resource_id) raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        acct = CloudAccount(name="aws-dup", provider="aws")
        db_session.add(acct)
        db_session.commit()

        r1 = CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="EC2", resource_id="i-same",
        )
        db_session.add(r1)
        db_session.commit()

        r2 = CloudResource(
            account_id=acct.id, provider="aws", region="us-west-2",
            resource_type="EC2", resource_id="i-same",
        )
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestGetEnabledAccounts:
    """Tests for get_enabled_accounts query pattern."""

    def test_get_enabled_accounts_returns_list(self, db_session: Session):
        """Only enabled accounts are returned; disabled ones are excluded."""
        aws = CloudAccount(name="a1", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
        azure = CloudAccount(name="a2", provider="azure", is_enabled=True, credentials={}, regions=["eastus"])
        disabled = CloudAccount(name="a3", provider="gcp", is_enabled=False, credentials={}, regions=[])
        db_session.add_all([aws, azure, disabled])
        db_session.commit()

        enabled = db_session.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
        assert len(enabled) == 2
        providers = {a.provider for a in enabled}
        assert providers == {"aws", "azure"}

    def test_get_enabled_accounts_empty(self, db_session: Session):
        """Returns empty list when no accounts exist."""
        enabled = db_session.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
        assert len(enabled) == 0


class TestSaveResourcesToCloudResource:
    """Tests for saving resources to CloudResource table."""

    def test_save_resources_creates_cloud_resource(self, db_session: Session):
        """CloudResource can be created and queried by account_id."""
        acct = CloudAccount(name="test-aws", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
        db_session.add(acct)
        db_session.commit()

        res = CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="compute", resource_id="arn:aws:ec2:us-east-1:123:instance/i-abc",
            name="web-1", tags={"Name": "web-1"}, raw_data={"InstanceId": "i-abc"},
            status="running",
        )
        db_session.add(res)
        db_session.commit()

        found = db_session.query(CloudResource).filter_by(account_id=acct.id).all()
        assert len(found) == 1
        assert found[0].provider == "aws"
        assert found[0].name == "web-1"
        assert found[0].status == "running"
        assert found[0].raw_data == {"InstanceId": "i-abc"}

    def test_save_resources_upsert_by_account_provider_resource_id(self, db_session: Session):
        """Same (account_id, provider, resource_id) cannot be duplicated."""
        from sqlalchemy.exc import IntegrityError

        acct = CloudAccount(name="upsert-test", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
        db_session.add(acct)
        db_session.commit()

        r1 = CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="compute", resource_id="i-123", name="v1",
        )
        db_session.add(r1)
        db_session.commit()

        r2 = CloudResource(
            account_id=acct.id, provider="aws", region="us-east-1",
            resource_type="compute", resource_id="i-123", name="v2",
        )
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_save_resources_multi_provider(self, db_session: Session):
        """Resources from different providers are stored separately."""
        aws_acct = CloudAccount(name="aws-acct", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"])
        azure_acct = CloudAccount(name="azure-acct", provider="azure", is_enabled=True, credentials={}, regions=["eastus"])
        db_session.add_all([aws_acct, azure_acct])
        db_session.commit()

        r1 = CloudResource(
            account_id=aws_acct.id, provider="aws", region="us-east-1",
            resource_type="compute", resource_id="i-abc", name="aws-vm",
        )
        r2 = CloudResource(
            account_id=azure_acct.id, provider="azure", region="eastus",
            resource_type="compute", resource_id="/subscriptions/123/vm/vm1", name="azure-vm",
        )
        db_session.add_all([r1, r2])
        db_session.commit()

        all_resources = db_session.query(CloudResource).all()
        assert len(all_resources) == 2
        providers = {r.provider for r in all_resources}
        assert providers == {"aws", "azure"}
