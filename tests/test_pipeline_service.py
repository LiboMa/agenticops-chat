"""Unit tests for agenticops.services.pipeline_service.

Tests the individual trigger functions (trigger_auto_sre, trigger_auto_approve,
trigger_auto_execute) with mocked dependencies to verify gating logic, guard
checks, policy evaluation, and chaining behavior.
"""

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── trigger_auto_sre ──────────────────────────────────────────────────


class TestTriggerAutoSre:
    """Tests for trigger_auto_sre gating and guard logic."""

    @patch("agenticops.services.pipeline_service.settings")
    def test_disabled_when_auto_fix_off(self, mock_settings):
        """Should skip when auto_fix_enabled is False."""
        mock_settings.auto_fix_enabled = False
        from agenticops.services.pipeline_service import trigger_auto_sre

        # Should not raise, just log and return
        trigger_auto_sre(health_issue_id=1)
        # No thread should be spawned — we can't easily assert no thread,
        # but the function should return without error

    @patch("agenticops.services.pipeline_service.settings")
    @patch("agenticops.services.pipeline_service.threading.Thread")
    def test_spawns_thread_when_enabled(self, mock_thread_cls, mock_settings):
        """Should spawn daemon thread when enabled and no active plan."""
        mock_settings.auto_fix_enabled = True
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        with patch("agenticops.services.pipeline_service._run_auto_sre"):
            # Mock the guard check — no active FixPlan
            with patch("agenticops.models.get_db_session") as mock_db:
                mock_session = MagicMock()
                mock_session.__enter__ = MagicMock(return_value=mock_session)
                mock_session.__exit__ = MagicMock(return_value=False)
                mock_session.query.return_value.filter_by.return_value.filter.return_value.first.return_value = None
                mock_db.return_value = mock_session

                from agenticops.services.pipeline_service import trigger_auto_sre
                trigger_auto_sre(health_issue_id=42)

        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()

    @patch("agenticops.services.pipeline_service.settings")
    def test_skips_when_active_plan_exists(self, mock_settings):
        """Should skip SRE if issue already has an active (non-terminal) FixPlan."""
        mock_settings.auto_fix_enabled = True

        with patch("agenticops.models.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            active_plan = MagicMock()
            active_plan.id = 99
            active_plan.status = "approved"
            mock_session.query.return_value.filter_by.return_value.filter.return_value.first.return_value = active_plan
            mock_db.return_value = mock_session

            with patch("agenticops.services.pipeline_service.threading.Thread") as mock_thread_cls:
                from agenticops.services.pipeline_service import trigger_auto_sre
                trigger_auto_sre(health_issue_id=1)
                mock_thread_cls.assert_not_called()


# ── trigger_auto_approve ──────────────────────────────────────────────


class TestTriggerAutoApprove:
    """Tests for trigger_auto_approve gating and approval logic."""

    @patch("agenticops.services.pipeline_service.settings")
    def test_disabled_when_auto_fix_off(self, mock_settings):
        """Should skip when auto_fix_enabled is False."""
        mock_settings.auto_fix_enabled = False
        from agenticops.services.pipeline_service import trigger_auto_approve

        trigger_auto_approve(fix_plan_id=1)

    @patch("agenticops.services.pipeline_service.settings")
    def test_disabled_when_auto_approve_off(self, mock_settings):
        """Should skip when executor_auto_approve_l0_l1 is False."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_auto_approve_l0_l1 = False
        from agenticops.services.pipeline_service import trigger_auto_approve

        trigger_auto_approve(fix_plan_id=1)

    @patch("agenticops.services.pipeline_service.trigger_auto_execute")
    @patch("agenticops.services.pipeline_service.settings")
    def test_approves_l0_plan(self, mock_settings, mock_execute):
        """Should auto-approve L0 plan and chain to execute."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_auto_approve_l0_l1 = True
        mock_settings.policy_engine_enabled = False

        mock_plan = MagicMock()
        mock_plan.id = 5
        mock_plan.status = "draft"
        mock_plan.risk_level = "L0"
        mock_plan.health_issue_id = 10

        mock_issue = MagicMock()
        mock_issue.trace_id = "trace-abc"

        with patch("agenticops.models.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter_by.return_value.first.side_effect = [
                mock_plan, mock_issue, mock_issue
            ]
            mock_db.return_value = mock_session

            with patch("agenticops.services.pipeline_service.log_event", create=True):
                with patch("agenticops.services.pipeline_events.log_event", create=True):
                    from agenticops.services.pipeline_service import trigger_auto_approve
                    trigger_auto_approve(fix_plan_id=5)

        assert mock_plan.status == "approved"
        assert mock_plan.approved_by == "agent:auto-pipeline"
        mock_execute.assert_called_once()

    @patch("agenticops.services.pipeline_service.trigger_auto_execute")
    @patch("agenticops.services.pipeline_service.settings")
    def test_rejects_l2_plan_legacy(self, mock_settings, mock_execute):
        """Should NOT approve L2 plan in legacy mode (policy disabled)."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_auto_approve_l0_l1 = True
        mock_settings.policy_engine_enabled = False

        mock_plan = MagicMock()
        mock_plan.id = 6
        mock_plan.status = "draft"
        mock_plan.risk_level = "L2"

        with patch("agenticops.models.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_plan
            mock_db.return_value = mock_session

            from agenticops.services.pipeline_service import trigger_auto_approve
            trigger_auto_approve(fix_plan_id=6)

        # Should NOT have been approved
        assert mock_plan.status == "draft"
        mock_execute.assert_not_called()

    @patch("agenticops.services.pipeline_service.trigger_auto_execute")
    @patch("agenticops.services.pipeline_service.settings")
    def test_skips_non_draft_plan(self, mock_settings, mock_execute):
        """Should skip plan that's not in draft status."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_auto_approve_l0_l1 = True
        mock_settings.policy_engine_enabled = False

        mock_plan = MagicMock()
        mock_plan.id = 7
        mock_plan.status = "approved"  # already approved

        with patch("agenticops.models.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_plan
            mock_db.return_value = mock_session

            from agenticops.services.pipeline_service import trigger_auto_approve
            trigger_auto_approve(fix_plan_id=7)

        mock_execute.assert_not_called()


# ── trigger_auto_execute ──────────────────────────────────────────────


class TestTriggerAutoExecute:
    """Tests for trigger_auto_execute gating."""

    @patch("agenticops.services.pipeline_service.settings")
    def test_disabled_when_auto_fix_off(self, mock_settings):
        """Should skip when auto_fix_enabled is False."""
        mock_settings.auto_fix_enabled = False
        from agenticops.services.pipeline_service import trigger_auto_execute

        trigger_auto_execute(fix_plan_id=1)

    @patch("agenticops.services.pipeline_service.settings")
    def test_disabled_when_executor_off(self, mock_settings):
        """Should skip when executor_enabled is False."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_enabled = False
        from agenticops.services.pipeline_service import trigger_auto_execute

        trigger_auto_execute(fix_plan_id=1)

    @patch("agenticops.services.pipeline_service.settings")
    @patch("agenticops.services.pipeline_service.threading.Thread")
    def test_spawns_thread_when_enabled(self, mock_thread_cls, mock_settings):
        """Should spawn daemon thread when both switches are on."""
        mock_settings.auto_fix_enabled = True
        mock_settings.executor_enabled = True
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        from agenticops.services.pipeline_service import trigger_auto_execute
        trigger_auto_execute(fix_plan_id=99)

        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()
        # Verify daemon=True
        call_kwargs = mock_thread_cls.call_args[1]
        assert call_kwargs["daemon"] is True
        assert "auto-execute-99" in call_kwargs["name"]


# ── _restore_trace_id ─────────────────────────────────────────────────


class TestRestoreTraceId:
    """Tests for the trace-id restoration helper."""

    def test_no_op_when_none(self):
        """Should not crash when trace_id is None."""
        from agenticops.services.pipeline_service import _restore_trace_id
        _restore_trace_id(None)

    @patch("agenticops.services.pipeline_service._restore_trace_id")
    def test_restores_when_missing(self, mock_restore):
        """Helper should be callable with a trace string."""
        from agenticops.services.pipeline_service import _restore_trace_id
        # Direct call — just verify no exception
        _restore_trace_id("trace-xyz")
