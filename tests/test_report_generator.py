"""Tests for report/generator.py — ReportGenerator daily/summary reports.

Expanded to cover: generate_anomaly_report, generate_inventory_report,
generate_network_health_report, _save_report, get_recent_reports, and
RCA section in _build_daily_report_md.

Target: coverage 30% → 60%+.
"""

import pytest
from datetime import datetime, timedelta, timezone
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

    def test_with_anomalies_and_rca(self, db_session):
        """RCA section rendered when matching RCA result exists."""
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.severity = "critical"
        mock_anomaly.title = "High Latency"
        mock_anomaly.resource_type = "ELB"
        mock_anomaly.resource_id = "elb-001"
        mock_anomaly.region = "us-east-1"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.status = "open"
        mock_anomaly.description = "P99 latency > 5s"
        mock_anomaly.id = 42

        mock_rca = MagicMock()
        mock_rca.health_issue_id = 42
        mock_rca.root_cause = "Backend pod OOMKilled"
        mock_rca.recommendations = ["Scale pods", "Increase memory limits", "Add HPA"]

        report = gen._build_daily_report_md(
            date=datetime.now(timezone.utc),
            resource_count=3,
            anomalies=[mock_anomaly],
            rca_results=[mock_rca],
        )
        assert "Root Cause Analysis" in report
        assert "Backend pod OOMKilled" in report
        assert "Scale pods" in report


# ============================================================================
# generate_anomaly_report
# ============================================================================


class TestGenerateAnomalyReport:
    def test_anomaly_report_basic(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 1
        mock_anomaly.title = "Disk Full"
        mock_anomaly.severity = "high"
        mock_anomaly.anomaly_type = "threshold_breach"
        mock_anomaly.status = "open"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.resource_id = "vol-123"
        mock_anomaly.resource_type = "EBS::Volume"
        mock_anomaly.region = "us-west-2"
        mock_anomaly.metric_name = "DiskUsage"
        mock_anomaly.expected_value = 80
        mock_anomaly.actual_value = 99
        mock_anomaly.deviation_percent = 23.75
        mock_anomaly.description = "Disk utilization at 99%"

        report = gen.generate_anomaly_report(mock_anomaly, save=False)
        assert "# Anomaly Report" in report
        assert "Disk Full" in report
        assert "HIGH" in report
        assert "EBS::Volume" in report
        assert "23.8%" in report
        assert "Disk utilization at 99%" in report

    def test_anomaly_report_with_rca(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 2
        mock_anomaly.title = "CPU Spike"
        mock_anomaly.severity = "critical"
        mock_anomaly.anomaly_type = "metric_deviation"
        mock_anomaly.status = "open"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.resource_id = "i-abc"
        mock_anomaly.resource_type = "EC2::Instance"
        mock_anomaly.region = "us-east-1"
        mock_anomaly.metric_name = "CPUUtilization"
        mock_anomaly.expected_value = 40
        mock_anomaly.actual_value = 98
        mock_anomaly.deviation_percent = 145.0
        mock_anomaly.description = "CPU at 98%"

        mock_rca = MagicMock()
        mock_rca.confidence = 0.85
        mock_rca.root_cause = "Runaway process consuming CPU"
        mock_rca.contributing_factors = ["Memory pressure", "No autoscaling"]
        mock_rca.recommendations = ["Kill runaway process", "Enable autoscaling"]

        report = gen.generate_anomaly_report(mock_anomaly, rca=mock_rca, save=False)
        assert "Root Cause Analysis" in report
        assert "85%" in report
        assert "Runaway process" in report
        assert "Memory pressure" in report
        assert "Kill runaway process" in report

    def test_anomaly_report_no_metrics(self, db_session):
        """Anomaly with None metric fields shows N/A."""
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 3
        mock_anomaly.title = "Unknown Issue"
        mock_anomaly.severity = "low"
        mock_anomaly.anomaly_type = "unknown"
        mock_anomaly.status = "open"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.resource_id = "r-1"
        mock_anomaly.resource_type = "Lambda"
        mock_anomaly.region = "eu-west-1"
        mock_anomaly.metric_name = None
        mock_anomaly.expected_value = None
        mock_anomaly.actual_value = None
        mock_anomaly.deviation_percent = None
        mock_anomaly.description = "Something happened"

        report = gen.generate_anomaly_report(mock_anomaly, save=False)
        assert "N/A" in report

    def test_anomaly_report_save(self, populated_db, tmp_path):
        """When save=True, report is persisted to DB and file."""
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 10
        mock_anomaly.title = "Test Save"
        mock_anomaly.severity = "medium"
        mock_anomaly.anomaly_type = "test"
        mock_anomaly.status = "open"
        mock_anomaly.detected_at = datetime.now(timezone.utc)
        mock_anomaly.resource_id = "r-save"
        mock_anomaly.resource_type = "S3::Bucket"
        mock_anomaly.region = "us-east-1"
        mock_anomaly.metric_name = None
        mock_anomaly.expected_value = None
        mock_anomaly.actual_value = None
        mock_anomaly.deviation_percent = None
        mock_anomaly.description = "Test"

        report = gen.generate_anomaly_report(mock_anomaly, save=True)
        assert "# Anomaly Report" in report

        # Verify file saved
        report_files = list(settings.reports_dir.glob("anomaly_*.md"))
        assert len(report_files) >= 1

        # Verify DB record
        session = get_session()
        try:
            db_report = session.query(Report).filter_by(report_type="anomaly").first()
            assert db_report is not None
            assert "Test Save" in db_report.title
        finally:
            session.close()


# ============================================================================
# generate_inventory_report
# ============================================================================


class TestGenerateInventoryReport:
    def test_inventory_report_basic(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        report = gen.generate_inventory_report(save=False)
        assert "# Resource Inventory Report" in report
        assert "Total Resources" in report
        assert "EC2::Instance" in report

    def test_inventory_report_with_account(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator(account=populated_db["account"])

        report = gen.generate_inventory_report(save=False)
        assert "# Resource Inventory Report" in report

    def test_inventory_report_empty_db(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        report = gen.generate_inventory_report(save=False)
        assert "Total Resources**: 0" in report

    def test_inventory_report_save(self, populated_db):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        report = gen.generate_inventory_report(save=True)
        report_files = list(settings.reports_dir.glob("inventory_*.md"))
        assert len(report_files) >= 1


# ============================================================================
# _save_report
# ============================================================================


class TestSaveReport:
    def test_save_creates_file_and_db_record(self, db_session, tmp_path):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        gen._save_report(
            report_type="test",
            title="Test Report",
            content="# Hello\n\nTest content.",
        )

        # Verify file
        report_files = list(settings.reports_dir.glob("test_*.md"))
        assert len(report_files) == 1
        assert "Hello" in report_files[0].read_text()

        # Verify DB record
        session = get_session()
        try:
            db_report = session.query(Report).filter_by(report_type="test").first()
            assert db_report is not None
            assert db_report.title == "Test Report"
        finally:
            session.close()

    def test_save_stores_summary_truncated(self, db_session, tmp_path):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        long_content = "x" * 1000
        gen._save_report(
            report_type="long",
            title="Long Report",
            content=long_content,
        )

        session = get_session()
        try:
            db_report = session.query(Report).filter_by(report_type="long").first()
            assert db_report is not None
            assert len(db_report.summary) <= 500
        finally:
            session.close()


# ============================================================================
# get_recent_reports
# ============================================================================


class TestGetRecentReports:
    def test_get_recent_empty(self, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()
        reports = gen.get_recent_reports()
        assert reports == []

    def test_get_recent_with_data(self, db_session, tmp_path):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        # Save a couple of reports
        gen._save_report("daily", "Daily 1", "content 1")
        gen._save_report("daily", "Daily 2", "content 2")
        gen._save_report("anomaly", "Anomaly 1", "content 3")

        all_reports = gen.get_recent_reports()
        assert len(all_reports) == 3

        daily_only = gen.get_recent_reports(report_type="daily")
        assert len(daily_only) == 2

        limited = gen.get_recent_reports(limit=1)
        assert len(limited) == 1

    def test_get_recent_ordering(self, db_session, tmp_path):
        """Reports returned in descending created_at order."""
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        gen._save_report("daily", "First", "a")
        gen._save_report("daily", "Second", "b")

        reports = gen.get_recent_reports(report_type="daily")
        assert reports[0].title == "Second"


# ============================================================================
# generate_daily_report with save=True
# ============================================================================


class TestDailyReportSave:
    def test_daily_report_saved_to_file(self, populated_db, tmp_path):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        report = gen.generate_daily_report(save=True)
        assert "# Daily Operations Report" in report

        report_files = list(settings.reports_dir.glob("daily_*.md"))
        assert len(report_files) >= 1

    def test_daily_report_saved_to_db(self, populated_db, tmp_path):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        gen.generate_daily_report(save=True)

        session = get_session()
        try:
            db_report = session.query(Report).filter_by(report_type="daily").first()
            assert db_report is not None
        finally:
            session.close()


# ============================================================================
# generate_network_health_report (mocked network tools)
# ============================================================================


class TestNetworkHealthReport:
    def _mock_topology(self):
        """Return a realistic topology JSON string."""
        import json
        return json.dumps({
            "vpcs": [
                {
                    "vpc_id": "vpc-123",
                    "name": "main-vpc",
                    "subnet_count": 4,
                }
            ],
            "transit_gateways": [{"tgw_id": "tgw-1"}],
            "peering_connections": [],
        })

    def _mock_vpc_topology(self):
        """Return a realistic VPC topology JSON string."""
        import json
        return json.dumps({
            "vpc_cidr": "10.0.0.0/16",
            "reachability_summary": {
                "public_subnet_count": 2,
                "private_subnet_count": 2,
                "has_internet_gateway": True,
                "nat_gateway_count": 1,
                "transit_gateway_attachments": 0,
                "vpc_endpoint_count": 3,
                "issues": [],
            },
            "blackhole_routes": [],
        })

    @patch("agenticops.tools.network_tools.analyze_vpc_topology")
    @patch("agenticops.tools.network_tools.describe_region_topology")
    @patch("agenticops.graph.algorithms.network_segments")
    @patch("agenticops.graph.algorithms.detect_anomalies")
    @patch("agenticops.graph.engine.InfraGraph")
    def test_network_report_basic(
        self, mock_graph_cls, mock_detect, mock_segments,
        mock_describe, mock_analyze_vpc, db_session
    ):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_describe.return_value = self._mock_topology()
        mock_analyze_vpc.return_value = self._mock_vpc_topology()

        mock_graph_instance = MagicMock()
        mock_graph_instance.build_from_vpc_topology.return_value = mock_graph_instance
        mock_graph_cls.return_value = mock_graph_instance

        mock_anomaly_report = MagicMock()
        mock_anomaly_report.anomalies = []
        mock_detect.return_value = mock_anomaly_report

        report = gen.generate_network_health_report(
            regions=["us-east-1"], save=False
        )
        assert "# Network Health Report" in report
        assert "us-east-1" in report
        assert "main-vpc" in report
        assert "Healthy" in report
        assert "Executive Summary" in report

    @patch("agenticops.tools.network_tools.analyze_vpc_topology")
    @patch("agenticops.tools.network_tools.describe_region_topology")
    @patch("agenticops.graph.algorithms.network_segments")
    @patch("agenticops.graph.algorithms.detect_anomalies")
    @patch("agenticops.graph.engine.InfraGraph")
    def test_network_report_with_anomalies(
        self, mock_graph_cls, mock_detect, mock_segments,
        mock_describe, mock_analyze_vpc, db_session
    ):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_describe.return_value = self._mock_topology()
        mock_analyze_vpc.return_value = self._mock_vpc_topology()

        mock_graph_instance = MagicMock()
        mock_graph_instance.build_from_vpc_topology.return_value = mock_graph_instance
        mock_graph_cls.return_value = mock_graph_instance

        mock_anomaly = MagicMock()
        mock_anomaly.model_dump.return_value = {
            "severity": "high",
            "type": "isolated_subnet",
            "description": "Subnet has no route to NAT/IGW",
        }

        mock_anomaly_report = MagicMock()
        mock_anomaly_report.anomalies = [mock_anomaly]
        mock_detect.return_value = mock_anomaly_report

        report = gen.generate_network_health_report(
            regions=["us-east-1"], save=False
        )
        assert "Issues Detected" in report
        assert "isolated_subnet" in report

    @patch("agenticops.tools.network_tools.describe_region_topology")
    def test_network_report_topology_failure(self, mock_describe, db_session):
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        mock_describe.side_effect = Exception("API unavailable")

        report = gen.generate_network_health_report(
            regions=["ap-southeast-1"], save=False
        )
        assert "Failed to collect topology" in report

    def test_network_report_default_region(self, db_session):
        """When no regions provided and no account, defaults to us-east-1."""
        from agenticops.report.generator import ReportGenerator
        gen = ReportGenerator()

        with patch("agenticops.tools.network_tools.describe_region_topology") as mock_describe:
            mock_describe.side_effect = Exception("skip")
            report = gen.generate_network_health_report(save=False)
            mock_describe.assert_called_once_with(region="us-east-1")
