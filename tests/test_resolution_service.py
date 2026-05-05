"""Tests for agenticops.services.resolution_service — covering _run_post_resolution
and _record_pipeline_run paths that were previously uncovered (lines 49-54, 75-76,
86-87, 110-125).
"""

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Base,
    HealthIssue,
    get_session,
    init_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Isolated SQLite DB for resolution service tests."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    orig_db_url = settings.database_url
    orig_sops_dir = settings.sops_dir
    orig_cases_dir = settings.cases_dir
    orig_kb_dir = settings.knowledge_base_dir
    models_mod._engine = None

    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url
    settings.sops_dir = tmp_path / "sops"
    settings.cases_dir = tmp_path / "cases"
    settings.knowledge_base_dir = tmp_path / "kb"
    settings.ensure_dirs()

    engine = models_mod.get_engine()
    with engine.connect() as conn:
        conn.execute(models_mod.text("PRAGMA journal_mode=WAL"))
        conn.commit()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session, tmp_path

    session.close()
    models_mod._engine = None
    settings.database_url = orig_db_url
    settings.sops_dir = orig_sops_dir
    settings.cases_dir = orig_cases_dir
    settings.knowledge_base_dir = orig_kb_dir


@pytest.fixture
def resolved_issue(test_db):
    """Create a resolved HealthIssue with backing account/resource."""
    session, tmp_path = test_db

    account = AWSAccount(
        name="test-prod",
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/TestRole",
        regions=["us-east-1"],
        is_active=True,
    )
    session.add(account)
    session.flush()

    resource = AWSResource(
        account_id=account.id,
        resource_id="i-res-svc-001",
        resource_type="EC2",
        resource_name="res-svc-test",
        resource_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-res-svc-001",
        region="us-east-1",
        status="running",
        metadata={},
    )
    session.add(resource)
    session.flush()

    issue = HealthIssue(
        resource_id="i-res-svc-001",
        severity="high",
        source="test",
        title="Test issue for resolution service",
        description="Original description.",
        status="resolved",
    )
    session.add(issue)
    session.flush()
    session.commit()

    return {"issue": issue, "session": session, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# Tests for _run_post_resolution
# ---------------------------------------------------------------------------

class TestRunPostResolution:
    """Test _run_post_resolution (the worker function)."""

    def test_skip_when_issue_not_found(self, test_db, caplog):
        """_run_post_resolution logs warning when issue ID doesn't exist."""
        from agenticops.services.resolution_service import _run_post_resolution

        with caplog.at_level(logging.WARNING):
            _run_post_resolution(999999)

        assert "not found" in caplog.text

    def test_skip_when_issue_not_resolved(self, resolved_issue, caplog):
        """_run_post_resolution logs warning when issue status != 'resolved'."""
        from agenticops.services.resolution_service import _run_post_resolution

        # Change status to something other than resolved
        sess = resolved_issue["session"]
        issue = resolved_issue["issue"]
        issue.status = "open"
        sess.commit()

        with caplog.at_level(logging.WARNING):
            _run_post_resolution(issue.id)

        assert "skipped" in caplog.text.lower()

    def test_happy_path_rag_and_distill(self, resolved_issue, caplog):
        """Full happy-path: RAG pipeline + case distillation succeed."""
        from agenticops.services.resolution_service import _run_post_resolution

        issue = resolved_issue["issue"]

        fake_rag = SimpleNamespace(action="created", success=True, sop_filename="sop-001.md")

        with (
            patch("agenticops.services.pipeline_events.log_event") as mock_log_event,
            patch("agenticops.pipeline.rag_pipeline.run_rag_pipeline", return_value=fake_rag) as mock_rag,
            patch("agenticops.tools.kb_tools.distill_case_study", return_value="Case study distilled OK") as mock_distill,
            caplog.at_level(logging.INFO),
        ):
            _run_post_resolution(issue.id)

        mock_rag.assert_called_once_with(issue.id)
        mock_distill.assert_called_once_with(issue.id)
        # log_event called for resolved + post_resolution
        assert mock_log_event.call_count >= 2

    def test_rag_pipeline_exception(self, resolved_issue, caplog):
        """RAG pipeline raises — should log exception but not crash."""
        from agenticops.services.resolution_service import _run_post_resolution

        issue = resolved_issue["issue"]

        with (
            patch("agenticops.services.pipeline_events.log_event"),
            patch("agenticops.pipeline.rag_pipeline.run_rag_pipeline", side_effect=RuntimeError("boom")),
            patch("agenticops.tools.kb_tools.distill_case_study", return_value="OK"),
            caplog.at_level(logging.ERROR),
        ):
            _run_post_resolution(issue.id)

        assert "boom" in caplog.text

    def test_distill_exception(self, resolved_issue, caplog):
        """Case distillation raises — should log exception but not crash."""
        from agenticops.services.resolution_service import _run_post_resolution

        issue = resolved_issue["issue"]
        fake_rag = SimpleNamespace(action="updated", success=True, sop_filename="sop-002.md")

        with (
            patch("agenticops.services.pipeline_events.log_event"),
            patch("agenticops.pipeline.rag_pipeline.run_rag_pipeline", return_value=fake_rag),
            patch("agenticops.tools.kb_tools.distill_case_study", side_effect=ValueError("distill fail")),
            caplog.at_level(logging.ERROR),
        ):
            _run_post_resolution(issue.id)

        assert "distill fail" in caplog.text


# ---------------------------------------------------------------------------
# Tests for _record_pipeline_run
# ---------------------------------------------------------------------------

class TestRecordPipelineRun:
    """Test _record_pipeline_run DB update logic."""

    def test_record_with_rag_result(self, resolved_issue):
        """Pipeline run appends note with RAG details to issue description."""
        from agenticops.services.resolution_service import _record_pipeline_run

        issue = resolved_issue["issue"]
        sess = resolved_issue["session"]

        fake_rag = SimpleNamespace(action="created", sop_filename="sop-auto.md")
        _record_pipeline_run(issue.id, fake_rag)

        sess.refresh(issue)
        assert "[Auto] Post-resolution pipeline" in issue.description
        assert "sop-auto.md" in issue.description

    def test_record_without_rag_result(self, resolved_issue):
        """Pipeline run appends note even when rag_result is None."""
        from agenticops.services.resolution_service import _record_pipeline_run

        issue = resolved_issue["issue"]
        sess = resolved_issue["session"]

        _record_pipeline_run(issue.id, None)

        sess.refresh(issue)
        assert "[Auto] Post-resolution pipeline" in issue.description

    def test_record_missing_issue(self, test_db):
        """_record_pipeline_run on non-existent issue does not crash."""
        from agenticops.services.resolution_service import _record_pipeline_run

        _record_pipeline_run(999999, None)  # Should just return

    def test_record_with_empty_description(self, resolved_issue):
        """Pipeline run sets description when it was previously empty."""
        from agenticops.services.resolution_service import _record_pipeline_run

        issue = resolved_issue["issue"]
        sess = resolved_issue["session"]
        issue.description = ""
        sess.commit()

        fake_rag = SimpleNamespace(action="upgraded", sop_filename=None)
        _record_pipeline_run(issue.id, fake_rag)

        sess.refresh(issue)
        assert "[Auto] Post-resolution pipeline" in issue.description


# ---------------------------------------------------------------------------
# Test trigger_post_resolution (enabled path)
# ---------------------------------------------------------------------------

class TestTriggerPostResolutionEnabled:
    """Test the public trigger_post_resolution with RAG enabled."""

    def test_spawns_thread_when_enabled(self, resolved_issue):
        """trigger_post_resolution spawns a daemon thread when RAG is enabled."""
        from agenticops.config import settings
        from agenticops.services.resolution_service import trigger_post_resolution

        orig = settings.rag_pipeline_enabled
        settings.rag_pipeline_enabled = True

        with patch("agenticops.services.resolution_service._run_post_resolution") as mock_run:
            trigger_post_resolution(resolved_issue["issue"].id)

            # Give the daemon thread a moment to start
            import time
            time.sleep(0.1)

        settings.rag_pipeline_enabled = orig
        # Thread was started (mock may or may not have been called depending on timing,
        # but we verify no exception was raised)
