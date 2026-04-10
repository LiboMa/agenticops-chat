"""Tests for services/executor_service.py — ExecutorService background daemon.

Targets coverage from 30% → 60%+.
"""

import threading
import time
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from agenticops.services.executor_service import ExecutorService


# ============================================================================
# Helpers
# ============================================================================


@pytest.fixture
def disabled_settings():
    """Settings with executor_enabled=False."""
    with patch("agenticops.services.executor_service.settings") as mock_settings:
        mock_settings.executor_enabled = False
        mock_settings.executor_total_timeout = 300
        yield mock_settings


@pytest.fixture
def enabled_settings():
    """Settings with executor_enabled=True."""
    with patch("agenticops.services.executor_service.settings") as mock_settings:
        mock_settings.executor_enabled = True
        mock_settings.executor_total_timeout = 5  # short for tests
        yield mock_settings


# ============================================================================
# Init & Properties
# ============================================================================


class TestExecutorServiceInit:
    def test_default_poll_interval(self):
        svc = ExecutorService()
        assert svc._poll_interval == 30

    def test_custom_poll_interval(self):
        svc = ExecutorService(poll_interval=10)
        assert svc._poll_interval == 10

    def test_initial_state(self):
        svc = ExecutorService()
        assert svc._thread is None
        assert svc._shutdown is False
        assert svc._active_executions == {}
        assert svc.is_running is False
        assert svc.active_count == 0


# ============================================================================
# Start / Stop lifecycle
# ============================================================================


class TestStartStop:
    def test_start_disabled(self, disabled_settings):
        """When executor_enabled=False, start() does nothing."""
        svc = ExecutorService()
        svc.start()
        assert svc._thread is None
        assert svc.is_running is False

    def test_start_enabled(self, enabled_settings):
        """When enabled, start() spawns a daemon thread."""
        svc = ExecutorService(poll_interval=60)
        # Patch _poll_loop so it exits immediately
        with patch.object(svc, "_poll_loop"):
            svc.start()
            assert svc._thread is not None
            # Clean up
            svc._shutdown = True
            svc._thread.join(timeout=2)
            svc._thread = None

    def test_start_idempotent(self, enabled_settings):
        """Calling start() twice doesn't spawn a second thread."""
        svc = ExecutorService(poll_interval=60)
        with patch.object(svc, "_poll_loop"):
            svc.start()
            first_thread = svc._thread
            svc.start()
            assert svc._thread is first_thread
            svc._shutdown = True
            first_thread.join(timeout=2)
            svc._thread = None

    def test_stop(self, enabled_settings):
        """stop() signals shutdown and joins thread."""
        svc = ExecutorService(poll_interval=60)

        def fake_poll():
            while not svc._shutdown:
                time.sleep(0.05)

        with patch.object(svc, "_poll_loop", side_effect=fake_poll):
            svc.start()
            assert svc.is_running is True
            svc.stop()
            assert svc._shutdown is True
            assert svc._thread is None

    def test_stop_without_start(self):
        """stop() when not started is safe."""
        svc = ExecutorService()
        svc.stop()  # no-op, no error
        assert svc._thread is None


# ============================================================================
# active_count
# ============================================================================


class TestActiveCount:
    def test_active_count_reflects_dict(self):
        svc = ExecutorService()
        assert svc.active_count == 0
        svc._active_executions[1] = MagicMock()
        assert svc.active_count == 1
        svc._active_executions[2] = MagicMock()
        assert svc.active_count == 2
        del svc._active_executions[1]
        assert svc.active_count == 1


# ============================================================================
# cancel_execution
# ============================================================================


class TestCancelExecution:
    def test_cancel_running_execution(self):
        """Cancel a running execution — sets status to aborted."""
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.id = 1
        mock_execution.status = "running"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_execution

        with patch("agenticops.services.executor_service.ExecutorService.cancel_execution.__module__"):
            pass

        # Use the actual method with mocked DB
        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            svc._active_executions[1] = MagicMock()
            result = svc.cancel_execution(1)

            assert result is True
            assert mock_execution.status == "aborted"
            assert mock_execution.error_message == "Cancelled by operator"
            mock_session.commit.assert_called_once()
            assert 1 not in svc._active_executions

    def test_cancel_nonexistent_execution(self):
        """Cancel returns False if execution not found."""
        svc = ExecutorService()

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = svc.cancel_execution(999)
            assert result is False

    def test_cancel_non_running_execution(self):
        """Cancel returns False if execution is not in 'running' status."""
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "succeeded"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_execution

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            result = svc.cancel_execution(1)
            assert result is False


# ============================================================================
# _poll_loop
# ============================================================================


class TestPollLoop:
    def test_poll_loop_calls_check_and_respects_shutdown(self):
        """_poll_loop calls _check_for_pending and exits on shutdown."""
        svc = ExecutorService(poll_interval=0)  # no sleep needed
        call_count = 0

        original_check = svc._check_for_pending

        def counting_check():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                svc._shutdown = True

        with patch.object(svc, "_check_for_pending", side_effect=counting_check):
            with patch("agenticops.services.executor_service.time.sleep"):
                svc._poll_loop()

        assert call_count >= 2

    def test_poll_loop_handles_exception(self):
        """_poll_loop catches exceptions and continues."""
        svc = ExecutorService(poll_interval=0)
        call_count = 0

        def failing_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("db error")
            svc._shutdown = True

        with patch.object(svc, "_check_for_pending", side_effect=failing_check):
            with patch("agenticops.services.executor_service.time.sleep"):
                svc._poll_loop()

        assert call_count >= 2  # survived the exception


# ============================================================================
# _check_for_pending
# ============================================================================


class TestCheckForPending:
    def test_no_pending_executions(self):
        """No pending executions → no dispatch."""
        svc = ExecutorService()

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            with patch.object(svc, "_dispatch") as mock_dispatch:
                svc._check_for_pending()
                mock_dispatch.assert_not_called()

    def test_pending_found_and_claimed(self):
        """Pending execution found, claimed atomically, dispatched."""
        svc = ExecutorService()

        mock_pending = MagicMock()
        mock_pending.id = 42
        mock_pending.fix_plan_id = 7

        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = mock_pending
        mock_session.execute.return_value = mock_result

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            with patch("sqlalchemy.update"):
                with patch.object(svc, "_dispatch") as mock_dispatch:
                    svc._check_for_pending()
                    mock_dispatch.assert_called_once_with(42, 7)
                    mock_session.commit.assert_called()

    def test_pending_already_claimed_by_another(self):
        """If UPDATE rowcount=0, another worker claimed it → no dispatch."""
        svc = ExecutorService()

        mock_pending = MagicMock()
        mock_pending.id = 42
        mock_pending.fix_plan_id = 7

        mock_result = MagicMock()
        mock_result.rowcount = 0

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = mock_pending
        mock_session.execute.return_value = mock_result

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            with patch("sqlalchemy.update"):
                with patch.object(svc, "_dispatch") as mock_dispatch:
                    svc._check_for_pending()
                    mock_dispatch.assert_not_called()


# ============================================================================
# _dispatch
# ============================================================================


class TestDispatch:
    def test_dispatch_creates_worker_and_watchdog(self):
        """_dispatch spawns worker + watchdog threads."""
        svc = ExecutorService()

        with patch.object(svc, "_run_executor"):
            with patch.object(svc, "_timeout_watchdog"):
                svc._dispatch(10, 5)

                # Worker thread should be in active_executions
                assert 10 in svc._active_executions
                worker = svc._active_executions[10]
                assert worker.daemon is True
                assert "executor-worker-10" in worker.name

                # Wait for threads to finish
                time.sleep(0.2)


# ============================================================================
# _run_executor
# ============================================================================


class TestRunExecutor:
    def test_successful_execution(self):
        """executor_agent called successfully."""
        svc = ExecutorService()
        svc._active_executions[1] = MagicMock()

        with patch("agenticops.agents.executor_agent.executor_agent", return_value="success"):
            svc._run_executor(1, 5)

        # Should be removed from active after completion
        assert 1 not in svc._active_executions

    def test_crashed_execution(self):
        """executor_agent raises → _mark_crashed called."""
        svc = ExecutorService()
        svc._active_executions[1] = MagicMock()

        with patch(
            "agenticops.agents.executor_agent.executor_agent",
            side_effect=RuntimeError("agent crashed"),
        ):
            with patch.object(svc, "_mark_crashed") as mock_mark:
                svc._run_executor(1, 5)
                mock_mark.assert_called_once_with(1, 5, "agent crashed")

        assert 1 not in svc._active_executions


# ============================================================================
# _mark_crashed / _mark_timed_out
# ============================================================================


class TestMarkCrashed:
    def test_mark_crashed_updates_db(self):
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "running"
        mock_plan = MagicMock()

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.side_effect = [
            mock_execution,
            mock_plan,
        ]

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            svc._mark_crashed(1, 5, "out of memory")

            assert mock_execution.status == "failed"
            assert "out of memory" in mock_execution.error_message
            assert mock_execution.completed_at is not None
            assert mock_plan.status == "failed"
            mock_session.commit.assert_called_once()

    def test_mark_crashed_skips_non_running(self):
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "succeeded"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_execution

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            svc._mark_crashed(1, 5, "error")
            # status should not change
            assert mock_execution.status == "succeeded"

    def test_mark_crashed_no_plan(self):
        """If fix_plan not found, still marks execution as failed."""
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "running"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.side_effect = [
            mock_execution,
            None,  # no plan found
        ]

        with patch("agenticops.models.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            svc._mark_crashed(1, 5, "error")
            assert mock_execution.status == "failed"


class TestMarkTimedOut:
    def test_mark_timed_out_updates_db(self):
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "running"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_execution

        with patch("agenticops.services.executor_service.settings") as mock_settings:
            mock_settings.executor_total_timeout = 300

            with patch("agenticops.models.get_db_session") as mock_get_db:
                mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

                svc._mark_timed_out(1)

                assert mock_execution.status == "failed"
                assert "300s" in mock_execution.error_message
                assert mock_execution.completed_at is not None
                mock_session.commit.assert_called_once()

    def test_mark_timed_out_skips_non_running(self):
        svc = ExecutorService()

        mock_execution = MagicMock()
        mock_execution.status = "aborted"

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_execution

        with patch("agenticops.services.executor_service.settings") as mock_settings:
            mock_settings.executor_total_timeout = 300

            with patch("agenticops.models.get_db_session") as mock_get_db:
                mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

                svc._mark_timed_out(1)
                assert mock_execution.status == "aborted"  # unchanged


# ============================================================================
# _timeout_watchdog
# ============================================================================


class TestTimeoutWatchdog:
    def test_watchdog_marks_timeout_if_still_alive(self):
        """If worker is still alive after timeout, mark as timed out."""
        svc = ExecutorService()

        # Create a long-running thread
        stop_event = threading.Event()
        worker = threading.Thread(target=lambda: stop_event.wait(10), daemon=True)
        worker.start()
        svc._active_executions[1] = worker

        with patch("agenticops.services.executor_service.settings") as mock_settings:
            mock_settings.executor_total_timeout = 0.1  # very short

            with patch.object(svc, "_mark_timed_out") as mock_mark:
                svc._timeout_watchdog(1, worker)
                mock_mark.assert_called_once_with(1)

        assert 1 not in svc._active_executions
        stop_event.set()
        worker.join(timeout=2)

    def test_watchdog_no_timeout_if_worker_finishes(self):
        """If worker finishes before timeout, no mark."""
        svc = ExecutorService()

        worker = threading.Thread(target=lambda: None, daemon=True)
        worker.start()
        worker.join(timeout=2)

        with patch("agenticops.services.executor_service.settings") as mock_settings:
            mock_settings.executor_total_timeout = 10

            with patch.object(svc, "_mark_timed_out") as mock_mark:
                svc._timeout_watchdog(1, worker)
                mock_mark.assert_not_called()
