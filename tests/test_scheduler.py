"""Tests for scheduler/scheduler.py — currently at 0% coverage."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from agenticops.scheduler.scheduler import CronParser, Scheduler, Schedule, ScheduleExecution
from agenticops.models import Base


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing with full isolation."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Save original state
    orig_db_url = settings.database_url
    orig_engine = models_mod._engine

    # Reset singleton engine
    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    from agenticops.models import get_session
    session = get_session()
    yield session
    session.close()

    # Restore original state — prevents leak to subsequent tests
    models_mod._engine = None
    settings.database_url = orig_db_url


# ============================================================================
# CronParser Tests
# ============================================================================


class TestCronParser:
    """Test CronParser expression parsing and matching."""

    def test_parse_wildcard(self):
        """Every minute: * * * * *"""
        cron = CronParser("* * * * *")
        assert 0 in cron.minute
        assert 59 in cron.minute
        assert 12 in cron.hour

    def test_parse_specific_values(self):
        """Specific time: 30 2 * * *  → minute=30, hour=2."""
        cron = CronParser("30 2 * * *")
        assert cron.minute == {30}
        assert cron.hour == {2}

    def test_parse_step(self):
        """Every 15 minutes: */15 * * * *"""
        cron = CronParser("*/15 * * * *")
        assert cron.minute == {0, 15, 30, 45}

    def test_parse_range(self):
        """Range: 0 9-17 * * *"""
        cron = CronParser("0 9-17 * * *")
        assert cron.hour == set(range(9, 18))
        assert cron.minute == {0}

    def test_parse_list(self):
        """List values: 0 8,12,18 * * *"""
        cron = CronParser("0 8,12,18 * * *")
        assert cron.hour == {8, 12, 18}

    def test_parse_invalid_expression(self):
        """Too few fields should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronParser("* * *")

    def test_parse_too_many_fields(self):
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronParser("* * * * * *")

    def test_matches_true(self):
        """Test that matches() returns True for matching datetime."""
        cron = CronParser("30 14 * * *")
        # 2025-03-20 14:30 is a Thursday (weekday=3)
        dt = datetime(2025, 3, 20, 14, 30, 0)
        assert cron.matches(dt) is True

    def test_matches_false(self):
        """Test that matches() returns False for non-matching datetime."""
        cron = CronParser("30 14 * * *")
        dt = datetime(2025, 3, 20, 15, 30, 0)
        assert cron.matches(dt) is False

    def test_next_run_basic(self):
        """next_run should find the next matching time."""
        cron = CronParser("0 * * * *")  # Every hour on :00
        after = datetime(2025, 3, 20, 14, 30, 0)
        nxt = cron.next_run(after)
        assert nxt.minute == 0
        assert nxt.hour == 15
        assert nxt.day == 20

    def test_next_run_every_minute(self):
        """* * * * * should be within 1 minute."""
        cron = CronParser("* * * * *")
        after = datetime(2025, 3, 20, 14, 30, 0)
        nxt = cron.next_run(after)
        assert nxt == datetime(2025, 3, 20, 14, 31, 0)

    def test_next_run_wraps_day(self):
        """Verify next_run wraps to next day if needed."""
        cron = CronParser("0 6 * * *")  # 6:00 AM daily
        after = datetime(2025, 3, 20, 18, 0, 0)
        nxt = cron.next_run(after)
        assert nxt.day == 21
        assert nxt.hour == 6

    def test_weekday_filter(self):
        """0 9 * * 1  → Monday only at 9:00."""
        cron = CronParser("0 9 * * 1")
        # 2025-03-20 is Thursday
        after = datetime(2025, 3, 20, 10, 0, 0)
        nxt = cron.next_run(after)
        # Should be Monday 2025-03-24
        assert nxt.weekday() == 0  # Monday
        assert nxt.hour == 9


# ============================================================================
# Scheduler CRUD Tests (static methods)
# ============================================================================


class TestSchedulerCRUD:
    """Test Scheduler add/list/enable/disable/delete."""

    def test_add_schedule(self, db_session):
        sched = Scheduler.add_schedule(
            name="test-scan",
            pipeline_name="FullScan",
            cron_expression="0 2 * * *",
        )
        assert sched.name == "test-scan"
        assert sched.pipeline_name == "FullScan"
        assert sched.next_run_at is not None

    def test_add_duplicate_raises(self, db_session):
        Scheduler.add_schedule(
            name="dup-test",
            pipeline_name="FullScan",
            cron_expression="0 2 * * *",
        )
        with pytest.raises(ValueError, match="already exists"):
            Scheduler.add_schedule(
                name="dup-test",
                pipeline_name="FullScan",
                cron_expression="0 3 * * *",
            )

    def test_list_schedules(self, db_session):
        Scheduler.add_schedule(
            name="sched-a",
            pipeline_name="FullScan",
            cron_expression="0 1 * * *",
        )
        Scheduler.add_schedule(
            name="sched-b",
            pipeline_name="Monitoring",
            cron_expression="*/10 * * * *",
        )
        schedules = Scheduler.list_schedules()
        names = {s.name for s in schedules}
        assert "sched-a" in names
        assert "sched-b" in names

    def test_disable_schedule(self, db_session):
        Scheduler.add_schedule(
            name="to-disable",
            pipeline_name="FullScan",
            cron_expression="0 2 * * *",
        )
        result = Scheduler.disable_schedule("to-disable")
        assert result is True

    def test_disable_nonexistent(self, db_session):
        result = Scheduler.disable_schedule("no-such")
        assert result is False

    def test_enable_schedule(self, db_session):
        Scheduler.add_schedule(
            name="to-enable",
            pipeline_name="FullScan",
            cron_expression="0 2 * * *",
        )
        Scheduler.disable_schedule("to-enable")
        result = Scheduler.enable_schedule("to-enable")
        assert result is True

    def test_enable_nonexistent(self, db_session):
        result = Scheduler.enable_schedule("no-such")
        assert result is False

    def test_delete_schedule(self, db_session):
        Scheduler.add_schedule(
            name="to-delete",
            pipeline_name="FullScan",
            cron_expression="0 2 * * *",
        )
        result = Scheduler.delete_schedule("to-delete")
        assert result is True
        assert len(Scheduler.list_schedules()) == 0

    def test_delete_nonexistent(self, db_session):
        result = Scheduler.delete_schedule("no-such")
        assert result is False


# ============================================================================
# Scheduler start/stop
# ============================================================================


class TestSchedulerLifecycle:
    """Test Scheduler start and stop."""

    def test_start_stop(self, db_session):
        scheduler = Scheduler()
        scheduler.start()
        assert scheduler._running is True
        scheduler.stop()
        assert scheduler._running is False

    def test_double_start(self, db_session):
        scheduler = Scheduler()
        scheduler.start()
        scheduler.start()  # should log warning but not crash
        assert scheduler._running is True
        scheduler.stop()

    def test_stop_when_not_running(self, db_session):
        scheduler = Scheduler()
        scheduler.stop()  # should not crash
        assert scheduler._running is False
