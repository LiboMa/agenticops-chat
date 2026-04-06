"""Tests for report/generator.py — ReportGenerator daily/summary reports."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from agenticops.models import Base, get_session, Anomaly, CloudResource, RCAResult, Report
import agenticops.models as models_mod
from agenticops.config import settings


@pytest.fixture
def db_session(tmp_path):
    """Temporary database for report tests."""
    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test_report.db"
    settings.database_url = db_url
    settings.reports_dir = tmp_path / "reports"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def populated_db(db_session, tmp_path):
    """DB with some anomalies and resources."""
    from agenticops.models import CloudAccount

    # Create account
    account = CloudAccount(
        name="test-account",
        provider="aws",
        regions=["us-east-1"],
    )
    db_session.add(account)
    db_session.flush()

    # Create resources
    for i in range(5):
        db_session.add(CloudResource(
            resource_id=f"i-{i:017d}",
            resource_type="EC2::Instance",
            provider="aws",
            account_id=account.id,
            region="us-east-1",
            name=f"test-instance-{i}",
        ))

    # Create anomalies
    now = datetime.now(timezone.utc)
    for sev in ["critical", "high", "medium", "low"]:
        db_session.add(Anomaly(
            title=f"Test {sev} anomaly",
            description=f"A {sev} issue found",
            severity=sev,
            anomaly_type="metric_deviation",
            resource_type="EC2::Instance",
            resource_id=f"i-{sev}",
            region="us-east-1",
            detected_at=now,
            status="open",
        ))

    db_session.commit()
    return {"account": account, "session": db_session}


class TestReportGenerator:
    """Tests for ReportGenerator."""

    def test_init_no_account(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        assert gen.account is None

    def test_init_with_account(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator(account=populated_db["account"])
        assert gen.account is not None

    def test_generate_daily_report_returns_markdown(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "# Daily Operations Report" in report
        assert "Executive Summary" in report
        assert "Anomalies by Severity" in report

    def test_daily_report_contains_anomaly_counts(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "Critical" in report
        assert "High" in report
        assert "Medium" in report
        assert "Low" in report

    def test_daily_report_with_specific_date(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        date = datetime(2025, 6, 15, tzinfo=timezone.utc)
        report = gen.generate_daily_report(date=date, save=False)
        assert "2025-06-15" in report

    def test_daily_report_with_account_filter(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator(account=populated_db["account"])
        report = gen.generate_daily_report(save=False)
        assert "# Daily Operations Report" in report

    def test_daily_report_critical_high_section(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "Critical & High Severity Anomalies" in report

    def test_daily_report_resource_summary(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        report = gen.generate_daily_report(save=False)
        assert "Resource Summary" in report


class TestBuildDailyReportMd:
    """Test the markdown builder directly."""

    def test_empty_anomalies(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        report = gen._build_daily_report_md(
            date=datetime.now(timezone.utc),
            resource_count=10,
            anomalies=[],
            rca_results=[],
        )
        assert "Total Resources Monitored" in report
        assert "10" in report
        assert "Critical & High" not in report  # no critical/high anomalies

    def test_with_anomalies(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.severity = "critical"
        mock_anomaly.title = "CPU Spike"
        mock_anomaly.resource_type = "EC2::Instance"
        mock_anomaly.resource_id = "i-123"
        mock_anomaly.region = "us-east-1"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.status = "open"
        mock_anomaly.description = "CPU usage exceeded 95%"
        mock_anomaly.id = 1

        report = gen._build_daily_report_md(
            date=datetime.now(timezone.utc),
            resource_count=5,
            anomalies=[mock_anomaly],
            rca_results=[],
        )
        assert "CPU Spike" in report
        assert "CRITICAL" in report
