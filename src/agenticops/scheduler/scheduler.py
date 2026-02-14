"""Scheduler - Cron-based task scheduling for AgenticOps."""

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from agenticops.models import Base, get_db_session, init_db

logger = logging.getLogger(__name__)


# ============================================================================
# Schedule Models
# ============================================================================


class Schedule(Base):
    """Scheduled task configuration."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    pipeline_name: Mapped[str] = mapped_column(String(100))
    cron_expression: Mapped[str] = mapped_column(String(100))
    account_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ScheduleExecution(Base):
    """Execution log for scheduled tasks."""

    __tablename__ = "schedule_executions"
    __table_args__ = (
        Index("idx_schedule_execution_schedule", "schedule_id"),
        Index("idx_schedule_execution_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    status: Mapped[str] = mapped_column(String(20))  # running, completed, failed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ============================================================================
# Cron Parser
# ============================================================================


class CronParser:
    """Simple cron expression parser.

    Supports standard 5-field cron expressions:
    minute hour day-of-month month day-of-week

    Special values:
    - * : any value
    - */n : every n units
    - n : specific value
    - n,m : list of values
    - n-m : range of values
    """

    def __init__(self, expression: str):
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expression}")

        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.day = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.weekday = self._parse_field(parts[4], 0, 6)

    def _parse_field(self, field: str, min_val: int, max_val: int) -> set:
        """Parse a single cron field."""
        values = set()

        for part in field.split(","):
            if part == "*":
                values.update(range(min_val, max_val + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                values.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                start, end = map(int, part.split("-"))
                values.update(range(start, end + 1))
            else:
                values.add(int(part))

        return values

    def next_run(self, after: Optional[datetime] = None) -> datetime:
        """Calculate the next run time after the given datetime."""
        if after is None:
            after = datetime.utcnow()

        # Start from the next minute
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Search for the next matching time (up to 2 years)
        max_iterations = 525600  # minutes in a year * 2
        for _ in range(max_iterations):
            if (
                candidate.minute in self.minute
                and candidate.hour in self.hour
                and candidate.day in self.day
                and candidate.month in self.month
                and candidate.weekday() in self.weekday
            ):
                return candidate

            candidate += timedelta(minutes=1)

        raise ValueError("Could not find next run time within 2 years")

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches the cron expression."""
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.day
            and dt.month in self.month
            and dt.weekday() in self.weekday
        )


# ============================================================================
# Scheduler
# ============================================================================


class Scheduler:
    """Background scheduler for running pipelines on a cron schedule."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the scheduler in a background thread."""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("Scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop."""
        while self._running:
            try:
                self._check_schedules()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            # Wait for next minute
            self._stop_event.wait(60)

    def _check_schedules(self):
        """Check and execute due schedules."""
        now = datetime.utcnow()

        with get_db_session() as session:
            schedules = session.query(Schedule).filter_by(is_enabled=True).all()

            for schedule in schedules:
                try:
                    cron = CronParser(schedule.cron_expression)

                    # Check if it's time to run
                    if schedule.next_run_at and schedule.next_run_at <= now:
                        self._execute_schedule(schedule)

                        # Update next run time
                        schedule.last_run_at = now
                        schedule.next_run_at = cron.next_run(now)

                    # Initialize next_run_at if not set
                    elif schedule.next_run_at is None:
                        schedule.next_run_at = cron.next_run(now)

                except Exception as e:
                    logger.error(f"Error processing schedule '{schedule.name}': {e}")

    def _execute_schedule(self, schedule: Schedule):
        """Execute a scheduled pipeline."""
        from agenticops.models import AWSAccount
        from agenticops.pipeline import (
            FullScanPipeline,
            MonitoringPipeline,
            DailyReportPipeline,
        )

        logger.info(f"Executing scheduled pipeline: {schedule.name}")

        # Create execution record
        with get_db_session() as session:
            execution = ScheduleExecution(
                schedule_id=schedule.id,
                status="running",
                started_at=datetime.utcnow(),
            )
            session.add(execution)
            session.flush()
            execution_id = execution.id

        try:
            # Get account
            account = None
            if schedule.account_name:
                with get_db_session() as session:
                    account = session.query(AWSAccount).filter_by(
                        name=schedule.account_name
                    ).first()
            else:
                with get_db_session() as session:
                    account = session.query(AWSAccount).filter_by(is_active=True).first()

            # Get pipeline factory
            pipeline_factories = {
                "FullScan": FullScanPipeline,
                "FullScanPipeline": FullScanPipeline,
                "Monitoring": MonitoringPipeline,
                "MonitoringPipeline": MonitoringPipeline,
                "DailyReport": DailyReportPipeline,
                "DailyReportPipeline": DailyReportPipeline,
            }

            factory = pipeline_factories.get(schedule.pipeline_name)
            if not factory:
                raise ValueError(f"Unknown pipeline: {schedule.pipeline_name}")

            # Create and execute pipeline
            pipeline = factory(account)
            result = asyncio.run(pipeline.execute())

            # Update execution record
            with get_db_session() as session:
                execution = session.query(ScheduleExecution).filter_by(
                    id=execution_id
                ).first()
                if execution:
                    execution.status = "completed" if result.success else "failed"
                    execution.completed_at = datetime.utcnow()
                    execution.duration_ms = result.duration_ms
                    execution.result = {
                        "pipeline": result.pipeline_name,
                        "steps": [
                            {
                                "name": s.step_name,
                                "status": s.status.value,
                                "data": s.data,
                            }
                            for s in result.step_results
                        ],
                    }

            logger.info(f"Schedule '{schedule.name}' completed: {result.status.value}")

        except Exception as e:
            logger.error(f"Schedule '{schedule.name}' failed: {e}")

            with get_db_session() as session:
                execution = session.query(ScheduleExecution).filter_by(
                    id=execution_id
                ).first()
                if execution:
                    execution.status = "failed"
                    execution.completed_at = datetime.utcnow()
                    execution.error = str(e)

    @staticmethod
    def add_schedule(
        name: str,
        pipeline_name: str,
        cron_expression: str,
        account_name: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Schedule:
        """Add a new schedule."""
        init_db()

        # Validate cron expression
        cron = CronParser(cron_expression)
        next_run = cron.next_run()

        with get_db_session() as session:
            # Check if name already exists
            existing = session.query(Schedule).filter_by(name=name).first()
            if existing:
                raise ValueError(f"Schedule '{name}' already exists")

            schedule = Schedule(
                name=name,
                pipeline_name=pipeline_name,
                cron_expression=cron_expression,
                account_name=account_name,
                config=config or {},
                next_run_at=next_run,
            )
            session.add(schedule)
            session.flush()
            return schedule

    @staticmethod
    def list_schedules() -> list:
        """List all schedules."""
        init_db()

        with get_db_session() as session:
            return session.query(Schedule).all()

    @staticmethod
    def enable_schedule(name: str) -> bool:
        """Enable a schedule."""
        with get_db_session() as session:
            schedule = session.query(Schedule).filter_by(name=name).first()
            if not schedule:
                return False

            schedule.is_enabled = True

            # Update next run time
            cron = CronParser(schedule.cron_expression)
            schedule.next_run_at = cron.next_run()

            return True

    @staticmethod
    def disable_schedule(name: str) -> bool:
        """Disable a schedule."""
        with get_db_session() as session:
            schedule = session.query(Schedule).filter_by(name=name).first()
            if not schedule:
                return False

            schedule.is_enabled = False
            return True

    @staticmethod
    def delete_schedule(name: str) -> bool:
        """Delete a schedule."""
        with get_db_session() as session:
            schedule = session.query(Schedule).filter_by(name=name).first()
            if not schedule:
                return False

            session.delete(schedule)
            return True

    @staticmethod
    def run_now(name: str) -> Optional[ScheduleExecution]:
        """Manually trigger a schedule to run immediately."""
        init_db()

        with get_db_session() as session:
            schedule = session.query(Schedule).filter_by(name=name).first()
            if not schedule:
                return None

            # Create a temporary scheduler instance to run the schedule
            scheduler = Scheduler()
            scheduler._execute_schedule(schedule)

            # Return the latest execution
            return (
                session.query(ScheduleExecution)
                .filter_by(schedule_id=schedule.id)
                .order_by(ScheduleExecution.started_at.desc())
                .first()
            )
