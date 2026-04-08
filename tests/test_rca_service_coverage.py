"""Targeted tests for src/agenticops/services/rca_service.py — covering low-coverage paths."""

import sys
import pytest
import threading
from unittest.mock import patch, MagicMock
from types import ModuleType


def _make_db_module(get_db_session_mock):
    """Create a fake agenticops.database module with a get_db_session."""
    mod = ModuleType("agenticops.database")
    mod.get_db_session = get_db_session_mock
    return mod


class TestTriggerAutoRca:
    @patch("agenticops.services.rca_service.settings")
    def test_disabled_skips(self, mock_settings):
        mock_settings.auto_rca_enabled = False
        from agenticops.services.rca_service import trigger_auto_rca
        # Should return without spawning a thread
        trigger_auto_rca(1)

    @patch("agenticops.services.rca_service.threading.Thread")
    @patch("agenticops.services.rca_service.settings")
    def test_enabled_spawns_thread(self, mock_settings, mock_thread_cls):
        """When auto_rca_enabled=True and the DB module doesn't exist, the try/except falls through and thread is spawned."""
        mock_settings.auto_rca_enabled = True
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        from agenticops.services.rca_service import trigger_auto_rca
        # agenticops.database doesn't exist, so the try block fails and we proceed to thread spawn
        trigger_auto_rca(1)
        mock_thread.start.assert_called_once()

    @patch("agenticops.services.rca_service.threading.Thread")
    @patch("agenticops.services.rca_service.settings")
    def test_dismissed_issue_skipped(self, mock_settings, mock_thread_cls):
        mock_settings.auto_rca_enabled = True

        mock_issue = MagicMock()
        mock_issue.status = "dismissed"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_issue
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        mock_get_db = MagicMock(return_value=mock_session_ctx)
        fake_db_mod = _make_db_module(mock_get_db)

        with patch.dict(sys.modules, {"agenticops.database": fake_db_mod}):
            from agenticops.services.rca_service import trigger_auto_rca
            trigger_auto_rca(42)
            mock_thread_cls.assert_not_called()

    @patch("agenticops.services.rca_service.threading.Thread")
    @patch("agenticops.services.rca_service.settings")
    def test_db_check_failure_proceeds(self, mock_settings, mock_thread_cls):
        """If the DB check throws, RCA should still proceed."""
        mock_settings.auto_rca_enabled = True
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        mock_get_db = MagicMock(side_effect=Exception("db down"))
        fake_db_mod = _make_db_module(mock_get_db)

        with patch.dict(sys.modules, {"agenticops.database": fake_db_mod}):
            from agenticops.services.rca_service import trigger_auto_rca
            trigger_auto_rca(99, trace_id="trace-abc")
            mock_thread.start.assert_called_once()

    @patch("agenticops.services.rca_service.threading.Thread")
    @patch("agenticops.services.rca_service.settings")
    def test_active_issue_spawns_thread(self, mock_settings, mock_thread_cls):
        mock_settings.auto_rca_enabled = True
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        mock_issue = MagicMock()
        mock_issue.status = "open"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_issue
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        mock_get_db = MagicMock(return_value=mock_session_ctx)
        fake_db_mod = _make_db_module(mock_get_db)

        with patch.dict(sys.modules, {"agenticops.database": fake_db_mod}):
            from agenticops.services.rca_service import trigger_auto_rca
            trigger_auto_rca(10, trace_id="t-123")
            mock_thread.start.assert_called_once()


class TestRunAutoRca:
    @patch("agenticops.agents.rca_agent.rca_agent")
    @patch("agenticops.services.pipeline_events.log_event")
    def test_successful_rca(self, mock_log, mock_rca):
        mock_rca.return_value = {"summary": "root cause found"}
        from agenticops.services.rca_service import _run_auto_rca
        _run_auto_rca(1)
        mock_rca.assert_called_once_with(issue_id=1)

    @patch("agenticops.agents.rca_agent.rca_agent", side_effect=RuntimeError("agent crash"))
    @patch("agenticops.services.pipeline_events.log_event")
    def test_failed_rca_logs_event(self, mock_log, mock_rca):
        from agenticops.services.rca_service import _run_auto_rca
        _run_auto_rca(2, trace_id="t-fail")
        # Should log rca_completed with failed status
        calls = [c for c in mock_log.call_args_list if c[0][1] == "rca_completed"]
        assert len(calls) >= 1

    @patch("agenticops.agents.rca_agent.rca_agent")
    @patch("agenticops.services.pipeline_events.log_event")
    @patch("agenticops.config.get_trace_id", return_value=None)
    @patch("agenticops.config.set_trace_id")
    def test_trace_id_restored(self, mock_set, mock_get_tid, mock_log, mock_rca):
        mock_rca.return_value = "ok"
        from agenticops.services.rca_service import _run_auto_rca
        _run_auto_rca(3, trace_id="trace-xyz")
        mock_set.assert_called_with("trace-xyz")
