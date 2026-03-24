"""Tests for report/generator.py — currently at 0% coverage."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from agenticops.models import (
    Base,
    Anomaly,
    AWSAccount,
    AWSResource,
    HealthIssue,
    RCAResult,
    Report,
    get_session,
)
from agenticops.report.generator import ReportGenerator


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url
    settings.reports_dir = tmp_path / "reports"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir = tmp_path / "data"
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def account(db_session):
    """Create a test AWS account."""
    acct = AWSAccount(
        name="test-account",
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
        is_active=True,
    )
    db_session.add(acct)
    db_session.commit()
    return acct


@pytest.fixture
def sample_resources(db_session, account):
    """Create some test resources."""
    resources = []
    for i, rtype in enumerate(["ec2:instance", "rds:instance", "s3:bucket"]):
        r = AWSResource(
            resource_id=f"res-{i}",
            resource_type=rtype,
            resource_arn=f"arn:aws:{rtype}:us-east-1:123456789012:{rtype}/{i}",
            region="us-east-1",
            account_id=account.id,
            resource_name=f"test-resource-{i}",
        )
        resources.append(r)
        db_session.add(r)
    db_session.commit()
    return resources


@pytest.fixture
def sample_anomalies(db_session, sample_resources):
    """Create test anomalies with various severities."""
    now = datetime.now(timezone.utc)
    anomalies = []
    for i, (sev, title) in enumerate([
        ("critical", "EC2 CPU at 100%"),
        ("high", "RDS connection spike"),
        ("medium", "S3 latency increased"),
        ("low", "Minor config drift"),
    ]):
        a = Anomaly(
            title=title,
            description=f"Test anomaly {i}: {title}",
            severity=sev,
            anomaly_type="metric_spike",
            status="open",
            resource_type=sample_resources[i % len(sample_resources)].resource_type,
            resource_id=sample_resources[i % len(sample_resources)].resource_id,
            region="us-east-1",
            detected_at=now - timedelta(hours=i),
        )
        anomalies.append(a)
        db_session.add(a)
    db_session.commit()
    return anomalies


@pytest.fixture
def sample_rca(db_session, sample_anomalies):
    """Create RCA results for the critical anomaly via a HealthIssue."""
    now = datetime.now(timezone.utc)
    # RCAResult requires a HealthIssue, not a raw Anomaly
    hi = HealthIssue(
        resource_id=sample_anomalies[0].resource_id,
        severity="critical",
        source="metric_anomaly",
        title=sample_anomalies[0].title,
        description=sample_anomalies[0].description,
        status="open",
        detected_at=now,
    )
    db_session.add(hi)
    db_session.flush()
    rca = RCAResult(
        health_issue_id=hi.id,
        root_cause="CPU-bound process consuming all resources",
        recommendations=["Scale up instance", "Add autoscaling", "Investigate process"],
        confidence=0.92,
        created_at=now,
    )
    db_session.add(rca)
    db_session.commit()
    return rca


class TestReportGeneratorInit:
    """Test ReportGenerator initialization."""

    def test_init_without_account(self, db_session):
        gen = ReportGenerator()
        assert gen.account is None

    def test_init_with_account(self, db_session, account):
        gen = ReportGenerator(account=account)
        assert gen.account == account


class TestDailyReport:
    """Test daily report generation."""

    def test_generate_daily_report_empty(self, db_session):
        """Test daily report with no data."""
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "Daily Operations Report" in report
        assert "Total Resources Monitored" in report
        assert "Anomalies Detected" in report

    def test_generate_daily_report_with_data(
        self, db_session, account, sample_resources, sample_anomalies, sample_rca
    ):
        """Test daily report with resources, anomalies, and RCA."""
        gen = ReportGenerator(account=account)
        report = gen.generate_daily_report(save=False)
        assert "Daily Operations Report" in report
        assert "Executive Summary" in report
        assert "Resource Summary" in report
        assert "AgenticAIOps" in report

    def test_generate_daily_report_saved(self, db_session, account, sample_resources):
        """Test that save=True persists the report."""
        gen = ReportGenerator(account=account)
        report = gen.generate_daily_report(save=True)
        assert "Daily Operations Report" in report

        # Should have a Report row in the DB
        saved = db_session.query(Report).filter_by(report_type="daily").first()
        assert saved is not None

    def test_generate_daily_report_specific_date(self, db_session):
        """Test generating report for a specific date."""
        gen = ReportGenerator()
        specific_date = datetime(2025, 1, 15, 12, 0, 0)
        report = gen.generate_daily_report(date=specific_date, save=False)
        assert "2025-01-15" in report

    def test_daily_report_severity_table(self, db_session, sample_anomalies):
        """Test that daily report includes severity breakdown table."""
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "Critical" in report
        assert "High" in report
        assert "Medium" in report
        assert "Low" in report

    def test_daily_report_critical_anomaly_details(
        self, db_session, sample_anomalies, sample_rca
    ):
        """Test that critical/high anomalies are detailed."""
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        # Critical and high anomalies should appear with details
        assert "EC2 CPU at 100%" in report or "RDS connection spike" in report


class TestBuildDailyReportMd:
    """Test the markdown builder directly."""

    def test_build_no_anomalies(self, db_session):
        gen = ReportGenerator()
        md = gen._build_daily_report_md(
            date=datetime.now(timezone.utc),
            resource_count=10,
            anomalies=[],
            rca_results=[],
        )
        assert "Total Resources Monitored" in md
        assert "10" in md
        assert "Anomalies Detected" in md
        assert "0" in md


class TestAnomalyReport:
    """Test single-anomaly report generation."""

    def test_generate_anomaly_report(self, db_session, sample_anomalies):
        gen = ReportGenerator()
        report = gen.generate_anomaly_report(sample_anomalies[0], save=False)
        assert "Anomaly Report" in report
        assert sample_anomalies[0].title in report

    def test_generate_anomaly_report_with_rca(
        self, db_session, sample_anomalies, sample_rca
    ):
        gen = ReportGenerator()
        report = gen.generate_anomaly_report(
            sample_anomalies[0], rca=sample_rca, save=False
        )
        assert "Root Cause Analysis" in report
        assert "CPU-bound process" in report
