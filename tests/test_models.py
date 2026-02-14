"""Tests for database models."""

import pytest
from datetime import datetime

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Anomaly,
    MonitoringConfig,
    init_db,
    get_session,
    Base,
)


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    from agenticops.config import settings

    db_url = f"sqlite:///{tmp_path}/test.db"
    # Update the settings instance directly
    settings.database_url = db_url

    from agenticops.models import get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()


class TestAWSAccount:
    """Tests for AWSAccount model."""

    def test_create_account(self, db_session):
        """Test creating an AWS account."""
        account = AWSAccount(
            name="test-account",
            account_id="123456789012",
            role_arn="arn:aws:iam::123456789012:role/TestRole",
            regions=["us-east-1", "us-west-2"],
        )
        db_session.add(account)
        db_session.commit()

        assert account.id is not None
        assert account.name == "test-account"
        assert account.is_active is True
        assert len(account.regions) == 2

    def test_account_unique_name(self, db_session):
        """Test that account names must be unique."""
        account1 = AWSAccount(
            name="unique-account",
            account_id="111111111111",
            role_arn="arn:aws:iam::111111111111:role/Role1",
        )
        db_session.add(account1)
        db_session.commit()

        account2 = AWSAccount(
            name="unique-account",
            account_id="222222222222",
            role_arn="arn:aws:iam::222222222222:role/Role2",
        )
        db_session.add(account2)

        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestAWSResource:
    """Tests for AWSResource model."""

    def test_create_resource(self, db_session):
        """Test creating an AWS resource."""
        # First create an account
        account = AWSAccount(
            name="resource-test",
            account_id="333333333333",
            role_arn="arn:aws:iam::333333333333:role/Role",
        )
        db_session.add(account)
        db_session.commit()

        resource = AWSResource(
            account_id=account.id,
            resource_id="i-1234567890abcdef0",
            resource_type="EC2",
            resource_name="test-instance",
            region="us-east-1",
            status="running",
            resource_metadata={"instance_type": "t3.micro"},
            tags={"Environment": "test"},
        )
        db_session.add(resource)
        db_session.commit()

        assert resource.id is not None
        assert resource.resource_type == "EC2"
        assert resource.resource_metadata["instance_type"] == "t3.micro"


class TestAnomaly:
    """Tests for Anomaly model."""

    def test_create_anomaly(self, db_session):
        """Test creating an anomaly."""
        anomaly = Anomaly(
            resource_id="i-test123",
            resource_type="EC2",
            region="us-east-1",
            anomaly_type="threshold_breach",
            severity="high",
            title="High CPU on i-test123",
            description="CPU utilization exceeded 90%",
            metric_name="CPUUtilization",
            expected_value=70.0,
            actual_value=95.0,
            deviation_percent=35.7,
        )
        db_session.add(anomaly)
        db_session.commit()

        assert anomaly.id is not None
        assert anomaly.status == "open"
        assert anomaly.detected_at is not None
