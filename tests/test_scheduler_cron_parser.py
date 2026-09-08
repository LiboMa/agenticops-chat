"""Tests for agenticops.scheduler.scheduler module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from agenticops.scheduler.scheduler import CronParser, Schedule, ScheduleExecution, Scheduler


# ============================================================================
# CronParser Tests
# ============================================================================


class TestCronParserInit:
    """Test CronParser initialization and field parsing."""

    def test_valid_expression(self):
        cp = CronParser("0 * * * *")
        assert cp.minute == {0}
        assert cp.hour == set(range(0, 24))

    def test_invalid_expression_too_few_fields(self):
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronParser("0 * *")

    def test_invalid_expression_too_many_fields(self):
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronParser("0 * * * * *")

    def test_wildcard(self):
        cp = CronParser("* * * * *")
        assert cp.minute == set(range(0, 60))
        assert cp.hour == set(range(0, 24))
        assert cp.day == set(range(1, 32))
        assert cp.month == set(range(1, 13))
        assert cp.weekday == set(range(0, 7))

    def test_step_values(self):
        cp = CronParser("*/15 */6 * * *")
        assert cp.minute == {0, 15, 30, 45}
        assert cp.hour == {0, 6, 12, 18}

    def test_range_values(self):
        cp = CronParser("0 9-17 * * *")
        assert cp.hour == set(range(9, 18))

    def test_list_values(self):
        cp = CronParser("0,30 * * * *")
        assert cp.minute == {0, 30}

    def test_specific_value(self):
        cp = CronParser("5 3 * * *")
        assert cp.minute == {5}
        assert cp.hour == {3}

    def test_complex_expression(self):
        cp = CronParser("0,30 9-17 1,15 * 1-5")
        assert cp.minute == {0, 30}
        assert cp.hour == set(range(9, 18))
        assert cp.day == {1, 15}
        assert cp.month == set(range(1, 13))
        assert cp.weekday == {1, 2, 3, 4, 5}

    def test_weekday_specific(self):
        cp = CronParser("0 0 * * 0")
        assert cp.weekday == {0}  # Sunday

    def test_step_minutes(self):
        cp = CronParser("*/5 * * * *")
        assert cp.minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


class TestCronParserNextRun:
    """Test CronParser.next_run() method."""

    def test_next_minute(self):
        cp = CronParser("* * * * *")
        after = datetime(2026, 7, 14, 4, 0, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        assert result == datetime(2026, 7, 14, 4, 1, 0, tzinfo=timezone.utc)

    def test_next_hour(self):
        cp = CronParser("0 * * * *")
        after = datetime(2026, 7, 14, 4, 30, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        assert result == datetime(2026, 7, 14, 5, 0, 0, tzinfo=timezone.utc)

    def test_next_day(self):
        cp = CronParser("0 0 * * *")
        after = datetime(2026, 7, 14, 23, 30, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        assert result == datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc)

    def test_specific_weekday(self):
        # Python weekday(): 0=Monday, 1=Tuesday, ..., 6=Sunday
        cp = CronParser("0 9 * * 1")
        # 2026-07-14 is a Tuesday (weekday=1), so matches today but after 10:00
        after = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        # Next Tuesday is July 21
        assert result == datetime(2026, 7, 21, 9, 0, 0, tzinfo=timezone.utc)

    def test_next_month(self):
        cp = CronParser("0 0 1 * *")
        after = datetime(2026, 7, 2, 0, 0, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        assert result == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_defaults_to_now(self):
        cp = CronParser("* * * * *")
        result = cp.next_run()
        assert result > datetime.now(timezone.utc)

    def test_step_schedule(self):
        cp = CronParser("*/30 * * * *")
        after = datetime(2026, 7, 14, 4, 5, 0, tzinfo=timezone.utc)
        result = cp.next_run(after)
        assert result == datetime(2026, 7, 14, 4, 30, 0, tzinfo=timezone.utc)


class TestCronParserMatches:
    """Test CronParser.matches() method."""

    def test_matches_every_minute(self):
        cp = CronParser("* * * * *")
        dt = datetime(2026, 7, 14, 4, 0, 0, tzinfo=timezone.utc)
        assert cp.matches(dt) is True

    def test_matches_specific_time(self):
        cp = CronParser("30 9 * * *")
        assert cp.matches(datetime(2026, 7, 14, 9, 30, 0, tzinfo=timezone.utc)) is True
        assert cp.matches(datetime(2026, 7, 14, 9, 31, 0, tzinfo=timezone.utc)) is False

    def test_no_match_wrong_hour(self):
        cp = CronParser("0 9 * * *")
        dt = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
        assert cp.matches(dt) is False

    def test_matches_weekday(self):
        # Python weekday(): 0=Monday, 6=Sunday
        cp = CronParser("0 0 * * 6")  # Sunday = 6 in Python weekday
        # 2026-07-19 is a Sunday (weekday=6)
        assert cp.matches(datetime(2026, 7, 19, 0, 0, 0, tzinfo=timezone.utc)) is True
        # 2026-07-14 is a Tuesday (weekday=1)
        assert cp.matches(datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)) is False


# ============================================================================
# Schedule Model Tests
# ============================================================================


class TestScheduleModel:
    """Test Schedule and ScheduleExecution models."""

    def test_schedule_attributes(self):
        """Verify Schedule model has expected columns."""
        assert hasattr(Schedule, "name")
        assert hasattr(Schedule, "pipeline_name")
        assert hasattr(Schedule, "cron_expression")
        assert hasattr(Schedule, "is_enabled")
        assert hasattr(Schedule, "max_retries")
        assert hasattr(Schedule, "config")

    def test_schedule_execution_attributes(self):
        """Verify ScheduleExecution model has expected columns."""
        assert hasattr(ScheduleExecution, "schedule_id")
        assert hasattr(ScheduleExecution, "status")
        assert hasattr(ScheduleExecution, "started_at")
        assert hasattr(ScheduleExecution, "completed_at")
        assert hasattr(ScheduleExecution, "duration_ms")
        assert hasattr(ScheduleExecution, "retry_count")
        assert hasattr(ScheduleExecution, "result")
        assert hasattr(ScheduleExecution, "error")


# ============================================================================
# Scheduler Class Tests
# ============================================================================


class TestSchedulerLifecycle:
    """Test Scheduler start/stop lifecycle."""

    def test_init(self):
        s = Scheduler()
        assert s._running is False
        assert s._thread is None

    @patch("agenticops.scheduler.scheduler.get_db_session")
    def test_start_stop(self, mock_db):
        mock_session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.all.return_value = []

        s = Scheduler()
        s.start()
        assert s._running is True
        assert s._thread is not None

        s.stop()
        assert s._running is False
