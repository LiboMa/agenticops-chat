"""Tests for save_rca_result and get_rca_result metadata tools."""

import json
import pytest

from agenticops.models import (
    Base,
    HealthIssue,
    RCAResult,
    get_session,
)


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Reset singleton engine so each test gets a fresh DB
    models_mod._engine = None

    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


@pytest.fixture
def health_issue(db_session):
    """Create a test HealthIssue."""
    issue = HealthIssue(
        resource_id="i-test123",
        severity="high",
        source="cloudwatch_alarm",
        title="High CPU on i-test123",
        description="CPU utilization exceeded 90%",
        status="investigating",
    )
    db_session.add(issue)
    db_session.commit()
    return issue


class TestSaveRCAResult:
    """Tests for save_rca_result tool."""

    def test_save_basic_rca(self, db_session, health_issue):
        """Test saving a basic RCA result."""
        from agenticops.tools.metadata_tools import save_rca_result

        result = save_rca_result(
            health_issue_id=health_issue.id,
            root_cause="Runaway process causing CPU spike",
            confidence=0.85,
            contributing_factors='["No CPU limits", "Auto-scaling disabled"]',
            recommendations='["Set CPU limits", "Enable auto-scaling"]',
        )

        assert f"RCAResult #" in result
        assert "root_cause_identified" in result

        # Verify DB state
        rca = db_session.query(RCAResult).first()
        assert rca is not None
        assert rca.health_issue_id == health_issue.id
        assert rca.root_cause == "Runaway process causing CPU spike"
        assert rca.confidence == 0.85
        assert len(rca.contributing_factors) == 2
        assert len(rca.recommendations) == 2
        assert rca.fix_risk_level == "unknown"

        # Verify issue status updated
        db_session.refresh(health_issue)
        assert health_issue.status == "root_cause_identified"

    def test_save_full_rca(self, db_session, health_issue):
        """Test saving RCA with all fields populated."""
        from agenticops.tools.metadata_tools import save_rca_result

        result = save_rca_result(
            health_issue_id=health_issue.id,
            root_cause="Disk full on /var/log",
            confidence=0.95,
            contributing_factors='["Log rotation disabled", "Debug logging enabled"]',
            recommendations='["Enable log rotation", "Reduce log verbosity"]',
            fix_plan='{"steps": ["SSH to host", "Clean /var/log", "Enable logrotate"]}',
            fix_risk_level="low",
            sop_used="ec2-disk-full.md",
            similar_cases='["case-2024-disk-full.md"]',
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        )

        assert "RCAResult #" in result

        rca = db_session.query(RCAResult).first()
        assert rca.fix_risk_level == "low"
        assert rca.sop_used == "ec2-disk-full.md"
        assert len(rca.similar_cases) == 1
        assert rca.model_id == "us.anthropic.claude-sonnet-4-20250514-v1:0"
        assert "steps" in rca.fix_plan

    def test_save_rca_invalid_issue(self, db_session):
        """Test saving RCA for non-existent issue."""
        from agenticops.tools.metadata_tools import save_rca_result

        result = save_rca_result(
            health_issue_id=9999,
            root_cause="Test",
            confidence=0.5,
            contributing_factors="[]",
            recommendations="[]",
        )

        assert "not found" in result

    def test_save_rca_invalid_json_factors(self, db_session, health_issue):
        """Test that invalid JSON strings for factors are handled gracefully."""
        from agenticops.tools.metadata_tools import save_rca_result

        result = save_rca_result(
            health_issue_id=health_issue.id,
            root_cause="Test cause",
            confidence=0.5,
            contributing_factors="not valid json",
            recommendations="also not json",
        )

        assert "RCAResult #" in result

        rca = db_session.query(RCAResult).first()
        # Falls back to wrapping the string in a list
        assert rca.contributing_factors == ["not valid json"]
        assert rca.recommendations == ["also not json"]

    def test_confidence_clamped(self, db_session, health_issue):
        """Test that confidence is clamped to [0.0, 1.0]."""
        from agenticops.tools.metadata_tools import save_rca_result

        save_rca_result(
            health_issue_id=health_issue.id,
            root_cause="Test",
            confidence=1.5,
            contributing_factors="[]",
            recommendations="[]",
        )

        rca = db_session.query(RCAResult).first()
        assert rca.confidence == 1.0


class TestGetRCAResult:
    """Tests for get_rca_result tool."""

    def test_get_existing_rca(self, db_session, health_issue):
        """Test retrieving an existing RCA result."""
        rca = RCAResult(
            health_issue_id=health_issue.id,
            root_cause="Test root cause",
            confidence=0.8,
            contributing_factors=["factor1"],
            recommendations=["rec1"],
            model_id="test-model",
        )
        db_session.add(rca)
        db_session.commit()

        from agenticops.tools.metadata_tools import get_rca_result

        result = get_rca_result(health_issue_id=health_issue.id)
        data = json.loads(result)

        assert data["root_cause"] == "Test root cause"
        assert data["confidence"] == 0.8
        assert data["contributing_factors"] == ["factor1"]

    def test_get_rca_not_found(self, db_session):
        """Test retrieving RCA for non-existent issue."""
        from agenticops.tools.metadata_tools import get_rca_result

        result = get_rca_result(health_issue_id=9999)
        assert "No RCA result found" in result

    def test_get_latest_rca(self, db_session, health_issue):
        """Test that get_rca_result returns the latest result."""
        rca1 = RCAResult(
            health_issue_id=health_issue.id,
            root_cause="First analysis",
            confidence=0.4,
            model_id="test-model",
        )
        db_session.add(rca1)
        db_session.commit()

        rca2 = RCAResult(
            health_issue_id=health_issue.id,
            root_cause="Updated analysis",
            confidence=0.9,
            model_id="test-model",
        )
        db_session.add(rca2)
        db_session.commit()

        from agenticops.tools.metadata_tools import get_rca_result

        result = get_rca_result(health_issue_id=health_issue.id)
        data = json.loads(result)

        assert data["root_cause"] == "Updated analysis"
        assert data["confidence"] == 0.9
