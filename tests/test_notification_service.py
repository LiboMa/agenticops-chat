"""Tests for agenticops.services.notification_service — targeting 71% → 85%+ coverage.

Covers: notify_event (no-op when disabled), _buffer_or_send, flush_consolidated,
notify_issue_created, notify_rca_completed, notify_fix_planned, notify_fix_approved,
notify_execution_result, notify_report_saved, set_schedule_running, notify_im_origin.
"""

import threading
from unittest.mock import patch, MagicMock, ANY

import pytest

from agenticops.services.notification_service import (
    set_schedule_running,
    _buffer_or_send,
    flush_consolidated,
    notify_event,
    notify_issue_created,
    notify_rca_completed,
    notify_fix_planned,
    notify_fix_approved,
    notify_execution_result,
    notify_report_saved,
    notify_im_origin,
    _consolidated_buffer,
    _buffer_lock,
)


# ---------------------------------------------------------------------------
# notify_event — disabled path
# ---------------------------------------------------------------------------


class TestNotifyEventDisabled:
    """When notifications_enabled=False, no thread should be spawned."""

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.threading.Thread")
    def test_no_op_when_disabled(self, mock_thread, mock_settings):
        mock_settings.notifications_enabled = False
        notify_event("test_event", "subj", "body")
        mock_thread.assert_not_called()

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.threading.Thread")
    def test_thread_spawned_when_enabled(self, mock_thread, mock_settings):
        mock_settings.notifications_enabled = True
        mock_instance = MagicMock()
        mock_thread.return_value = mock_instance
        notify_event("test_event", "subj", "body", severity="high")
        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()


# ---------------------------------------------------------------------------
# _buffer_or_send
# ---------------------------------------------------------------------------


class TestBufferOrSend:
    def setup_method(self):
        with _buffer_lock:
            _consolidated_buffer.clear()

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.notify_event")
    def test_send_immediately_when_not_consolidated(self, mock_notify, mock_settings):
        mock_settings.notifications_consolidated = False
        _buffer_or_send(1, "issue_created", "subj", "body", "high")
        mock_notify.assert_called_once_with("issue_created", "subj", "body", "high")

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.notify_event")
    def test_suppressed_when_consolidated_issue_id_none(self, mock_notify, mock_settings):
        """When consolidated=True, ALL notifications are suppressed (even issue_id=None)."""
        mock_settings.notifications_consolidated = True
        _buffer_or_send(None, "report_saved", "subj", "body", None)
        mock_notify.assert_not_called()

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.notify_event")
    def test_suppressed_when_consolidated_and_issue_id(self, mock_notify, mock_settings):
        """When consolidated=True, per-issue notifications are suppressed (final report only)."""
        mock_settings.notifications_consolidated = True
        _buffer_or_send(42, "issue_created", "subj", "body", "medium")
        mock_notify.assert_not_called()

    def teardown_method(self):
        with _buffer_lock:
            _consolidated_buffer.clear()


# ---------------------------------------------------------------------------
# flush_consolidated
# ---------------------------------------------------------------------------


class TestFlushConsolidated:
    def setup_method(self):
        with _buffer_lock:
            _consolidated_buffer.clear()

    @patch("agenticops.services.notification_service.notify_event")
    def test_flush_empty_does_nothing(self, mock_notify):
        flush_consolidated(999)
        mock_notify.assert_not_called()

    @patch("agenticops.services.notification_service.notify_event")
    def test_flush_sends_pipeline_summary(self, mock_notify):
        with _buffer_lock:
            _consolidated_buffer[10] = [
                {"event_type": "issue_created", "subject": "s1", "body": "b1", "severity": "low"},
                {"event_type": "rca_completed", "subject": "s2", "body": "b2", "severity": "high"},
            ]
        flush_consolidated(10)
        mock_notify.assert_called_once()
        args = mock_notify.call_args
        assert "pipeline_summary" == args[0][0]
        assert "HIGH" in args[0][1]
        assert "2 stages" in args[0][1]
        assert 10 not in _consolidated_buffer

    def teardown_method(self):
        with _buffer_lock:
            _consolidated_buffer.clear()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    @patch("agenticops.services.notification_service._buffer_or_send")
    def test_notify_issue_created(self, mock_buf):
        notify_issue_created(1, "critical", "EC2 down", "i-abc123")
        mock_buf.assert_called_once()
        args = mock_buf.call_args
        assert args[1]["issue_id"] == 1 or args[0][0] == 1
        # Check event_type
        call_kwargs = mock_buf.call_args
        assert "issue_created" in str(call_kwargs)

    @patch("agenticops.services.notification_service._buffer_or_send")
    def test_notify_rca_completed(self, mock_buf):
        notify_rca_completed(5, "Memory leak in worker pod", 0.92)
        mock_buf.assert_called_once()
        assert "rca_completed" in str(mock_buf.call_args)

    @patch("agenticops.services.notification_service._buffer_or_send")
    def test_notify_fix_planned(self, mock_buf):
        notify_fix_planned(3, 10, "medium", "Scale up ASG")
        mock_buf.assert_called_once()
        assert "fix_planned" in str(mock_buf.call_args)

    @patch("agenticops.services.notification_service._buffer_or_send")
    def test_notify_fix_approved(self, mock_buf):
        notify_fix_approved(10, "admin@example.com", "low", issue_id=3)
        mock_buf.assert_called_once()
        assert "fix_approved" in str(mock_buf.call_args)

    @patch("agenticops.services.notification_service._buffer_or_send")
    @patch("agenticops.services.notification_service.flush_consolidated")
    def test_notify_execution_result_success(self, mock_flush, mock_buf):
        notify_execution_result(10, 3, "succeeded")
        mock_buf.assert_called_once()
        mock_flush.assert_called_once_with(3)

    @patch("agenticops.services.notification_service._buffer_or_send")
    @patch("agenticops.services.notification_service.flush_consolidated")
    def test_notify_execution_result_failure_sets_severity(self, mock_flush, mock_buf):
        notify_execution_result(10, 3, "failed", error="timeout")
        mock_buf.assert_called_once()
        # severity should be "high" for non-succeeded
        assert "high" in str(mock_buf.call_args)


class TestNotifyReportSaved:
    @patch("agenticops.services.notification_service._trigger_report_distribution")
    @patch("agenticops.services.notification_service.notify_event")
    @patch("agenticops.services.notification_service.settings")
    def test_report_saved_triggers_distribution(self, mock_settings, mock_notify, mock_dist):
        mock_settings.notifications_enabled = True
        notify_report_saved(1, "weekly", "Weekly Report")
        mock_notify.assert_called_once()
        mock_dist.assert_called_once_with(1, "weekly")

    @patch("agenticops.services.notification_service._trigger_report_distribution")
    @patch("agenticops.services.notification_service.notify_event")
    @patch("agenticops.services.notification_service.settings")
    def test_report_saved_no_distribution_when_disabled(self, mock_settings, mock_notify, mock_dist):
        mock_settings.notifications_enabled = False
        notify_report_saved(1, "weekly", "Weekly Report")
        mock_dist.assert_not_called()


# ---------------------------------------------------------------------------
# set_schedule_running
# ---------------------------------------------------------------------------


class TestSetScheduleRunning:
    def test_set_and_check(self):
        set_schedule_running(True)
        from agenticops.services.notification_service import _schedule_running
        assert _schedule_running.get(False) is True
        set_schedule_running(False)
        assert _schedule_running.get(False) is False


# ---------------------------------------------------------------------------
# notify_im_origin — disabled path
# ---------------------------------------------------------------------------


class TestNotifyImOrigin:
    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.threading.Thread")
    def test_no_op_when_disabled(self, mock_thread, mock_settings):
        mock_settings.notifications_enabled = False
        notify_im_origin(1, "rca_completed", "Root cause found")
        mock_thread.assert_not_called()

    @patch("agenticops.services.notification_service.settings")
    @patch("agenticops.services.notification_service.threading.Thread")
    def test_spawns_thread_when_enabled(self, mock_thread, mock_settings):
        mock_settings.notifications_enabled = True
        mock_instance = MagicMock()
        mock_thread.return_value = mock_instance
        notify_im_origin(1, "rca_completed", "Root cause found")
        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()
