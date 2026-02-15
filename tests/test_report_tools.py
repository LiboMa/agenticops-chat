"""Tests for save_report and list_reports tools."""

import json
import pytest

from agenticops.models import Base, Report, get_session


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Reset singleton engine so each test gets a fresh DB
    models_mod._engine = None

    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url

    # Point reports_dir to tmp_path so file writes are isolated
    settings.reports_dir = tmp_path / "reports"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


class TestSaveReport:
    """Tests for save_report tool."""

    def test_save_basic_report(self, db_session, tmp_path):
        """Test saving a basic daily report."""
        from agenticops.tools.report_tools import save_report

        result = save_report(
            report_type="daily",
            title="Daily Ops Report 2025-02-15",
            summary="3 issues detected, 1 critical resolved.",
            content_markdown="# Daily Report\n\n## Summary\n- 3 issues\n- 1 resolved",
        )

        assert "Report #" in result
        assert "DAILY" in result
        assert "Daily Ops Report" in result

        # Verify DB state
        report = db_session.query(Report).first()
        assert report is not None
        assert report.report_type == "daily"
        assert report.title == "Daily Ops Report 2025-02-15"
        assert report.summary == "3 issues detected, 1 critical resolved."
        assert "# Daily Report" in report.content_markdown
        assert report.file_path is not None
        assert report.report_metadata == {}

    def test_save_report_creates_file(self, db_session, tmp_path):
        """Test that save_report writes a .md file to reports_dir."""
        from agenticops.tools.report_tools import save_report
        from pathlib import Path

        save_report(
            report_type="incident",
            title="Incident Report",
            summary="Critical EC2 failure.",
            content_markdown="# Incident\n\nEC2 i-123 went down.",
        )

        report = db_session.query(Report).first()
        filepath = Path(report.file_path)
        assert filepath.exists()
        assert filepath.suffix == ".md"
        assert "incident-" in filepath.name
        content = filepath.read_text()
        assert "# Incident" in content

    def test_save_report_with_metadata(self, db_session):
        """Test saving report with custom metadata."""
        from agenticops.tools.report_tools import save_report

        result = save_report(
            report_type="inventory",
            title="Inventory Report",
            summary="15 resources across 2 regions.",
            content_markdown="# Inventory\n\n15 resources.",
            report_metadata='{"region_count": 2, "resource_count": 15}',
        )

        assert "Report #" in result

        report = db_session.query(Report).first()
        assert report.report_metadata == {"region_count": 2, "resource_count": 15}

    def test_save_report_invalid_type(self, db_session):
        """Test that invalid report_type is rejected."""
        from agenticops.tools.report_tools import save_report

        result = save_report(
            report_type="weekly",
            title="Test",
            summary="Test",
            content_markdown="Test",
        )

        assert "Invalid report_type" in result
        assert "weekly" in result

    def test_save_report_invalid_metadata_json(self, db_session):
        """Test that invalid JSON metadata defaults to empty dict."""
        from agenticops.tools.report_tools import save_report

        result = save_report(
            report_type="daily",
            title="Test Report",
            summary="Test",
            content_markdown="# Test",
            report_metadata="not valid json",
        )

        assert "Report #" in result

        report = db_session.query(Report).first()
        assert report.report_metadata == {}

    def test_save_report_title_truncation(self, db_session):
        """Test that titles longer than 200 chars are truncated."""
        from agenticops.tools.report_tools import save_report

        long_title = "A" * 250

        save_report(
            report_type="daily",
            title=long_title,
            summary="Test",
            content_markdown="# Test",
        )

        report = db_session.query(Report).first()
        assert len(report.title) == 200


class TestListReports:
    """Tests for list_reports tool."""

    def test_list_empty(self, db_session):
        """Test listing when no reports exist."""
        from agenticops.tools.report_tools import list_reports

        result = list_reports()
        assert "No reports found" in result

    def test_list_all_reports(self, db_session):
        """Test listing all reports."""
        from agenticops.tools.report_tools import save_report, list_reports

        save_report(
            report_type="daily",
            title="Report 1",
            summary="Summary 1",
            content_markdown="# Report 1",
        )
        save_report(
            report_type="incident",
            title="Report 2",
            summary="Summary 2",
            content_markdown="# Report 2",
        )

        result = list_reports()
        data = json.loads(result)

        assert len(data) == 2
        # Ordered by created_at desc
        assert data[0]["title"] == "Report 2"
        assert data[1]["title"] == "Report 1"

    def test_list_filtered_by_type(self, db_session):
        """Test listing reports filtered by type."""
        from agenticops.tools.report_tools import save_report, list_reports

        save_report(
            report_type="daily",
            title="Daily 1",
            summary="S",
            content_markdown="# D1",
        )
        save_report(
            report_type="incident",
            title="Incident 1",
            summary="S",
            content_markdown="# I1",
        )
        save_report(
            report_type="daily",
            title="Daily 2",
            summary="S",
            content_markdown="# D2",
        )

        result = list_reports(report_type="daily")
        data = json.loads(result)

        assert len(data) == 2
        assert all(r["report_type"] == "daily" for r in data)

    def test_list_filtered_empty(self, db_session):
        """Test listing with filter that matches nothing."""
        from agenticops.tools.report_tools import save_report, list_reports

        save_report(
            report_type="daily",
            title="Daily 1",
            summary="S",
            content_markdown="# D1",
        )

        result = list_reports(report_type="incident")
        assert "No reports found" in result
        assert "type=incident" in result

    def test_list_with_limit(self, db_session):
        """Test that limit caps results."""
        from agenticops.tools.report_tools import save_report, list_reports

        for i in range(5):
            save_report(
                report_type="daily",
                title=f"Report {i}",
                summary="S",
                content_markdown=f"# R{i}",
            )

        result = list_reports(limit=3)
        data = json.loads(result)

        assert len(data) == 3

    def test_list_report_fields(self, db_session):
        """Test that list_reports returns expected fields."""
        from agenticops.tools.report_tools import save_report, list_reports

        save_report(
            report_type="daily",
            title="Field Test",
            summary="Test summary",
            content_markdown="# Test",
        )

        result = list_reports()
        data = json.loads(result)
        report = data[0]

        assert "id" in report
        assert "report_type" in report
        assert "title" in report
        assert "summary" in report
        assert "file_path" in report
        assert "created_at" in report
