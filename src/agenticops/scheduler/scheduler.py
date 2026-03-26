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

        # Phase 1: read all enabled schedules and close the session
        due: list[dict] = []
        init_only: list[tuple[int, datetime]] = []

        with get_db_session() as session:
            schedules = session.query(Schedule).filter_by(is_enabled=True).all()
            for s in schedules:
                try:
                    cron = CronParser(s.cron_expression)
                    if s.next_run_at and s.next_run_at <= now:
                        # Snapshot the fields we need — no lazy access later
                        due.append({
                            "id": s.id,
                            "name": s.name,
                            "pipeline_name": s.pipeline_name,
                            "account_name": s.account_name,
                            "config": dict(s.config) if s.config else {},
                            "next_run": cron.next_run(now),
                        })
                    elif s.next_run_at is None:
                        init_only.append((s.id, cron.next_run(now)))
                except Exception as e:
                    logger.error(f"Error parsing schedule '{s.name}': {e}")

            # Initialize next_run_at for newly created schedules
            for sid, next_run in init_only:
                obj = session.query(Schedule).filter_by(id=sid).first()
                if obj:
                    obj.next_run_at = next_run

        # Phase 2: execute due schedules outside any session
        for info in due:
            try:
                self._execute_schedule_by_info(info)
            except Exception as e:
                logger.error(f"Error executing schedule '{info['name']}': {e}")

            # Phase 3: update last_run_at / next_run_at in a fresh session
            try:
                with get_db_session() as session:
                    obj = session.query(Schedule).filter_by(id=info["id"]).first()
                    if obj:
                        obj.last_run_at = now
                        obj.next_run_at = info["next_run"]
            except Exception as e:
                logger.error(f"Error updating schedule '{info['name']}': {e}")

    def _execute_schedule(self, schedule: Schedule):
        """Execute a scheduled pipeline from an ORM object.

        Extracts plain data from the Schedule, then delegates to
        ``_execute_schedule_by_info`` so no SQLAlchemy lazy-load happens
        during the (potentially long-running) pipeline execution.
        """
        info = {
            "id": schedule.id,
            "name": schedule.name,
            "pipeline_name": schedule.pipeline_name,
            "account_name": schedule.account_name,
            "config": dict(schedule.config) if schedule.config else {},
        }
        self._execute_schedule_by_info(info)

    def _execute_schedule_by_info(self, info: dict):
        """Execute a scheduled pipeline from a plain dict (no ORM dependency).

        ``info`` keys: id, name, pipeline_name, account_name, config.
        """
        from agenticops.models import CloudAccount
        from agenticops.pipeline import (
            FullScanPipeline,
            MonitoringPipeline,
            DailyReportPipeline,
            HealthPatrolPipeline,
        )

        schedule_id = info["id"]
        schedule_name = info["name"]
        pipeline_name = info["pipeline_name"]
        account_name = info.get("account_name")
        config = info.get("config") or {}

        logger.info(f"Executing scheduled pipeline: {schedule_name}")

        # Create execution record
        with get_db_session() as session:
            execution = ScheduleExecution(
                schedule_id=schedule_id,
                status="running",
                started_at=datetime.utcnow(),
            )
            session.add(execution)
            session.flush()
            execution_id = execution.id

        # AgentChain: prompt-driven execution via Main Agent
        if pipeline_name == "AgentChain":
            # _execute_agent_chain still needs a Schedule ORM; load fresh
            with get_db_session() as session:
                schedule_obj = session.query(Schedule).filter_by(id=schedule_id).first()
                if schedule_obj:
                    session.expunge(schedule_obj)
            if schedule_obj:
                self._execute_agent_chain(schedule_obj, execution_id)
            return

        try:
            # Get accounts — expunge so they can be used outside the session
            accounts = []
            if account_name:
                with get_db_session() as session:
                    acct = session.query(CloudAccount).filter_by(
                        name=account_name
                    ).first()
                    if acct:
                        session.expunge(acct)
                        accounts = [acct]
            else:
                with get_db_session() as session:
                    all_accts = session.query(CloudAccount).filter_by(is_enabled=True).all()
                    for a in all_accts:
                        session.expunge(a)
                    accounts = all_accts

            if not accounts:
                raise ValueError("No enabled accounts found")

            # Get pipeline factory
            pipeline_factories = {
                "FullScan": FullScanPipeline,
                "FullScanPipeline": FullScanPipeline,
                "Monitoring": MonitoringPipeline,
                "MonitoringPipeline": MonitoringPipeline,
                "DailyReport": DailyReportPipeline,
                "DailyReportPipeline": DailyReportPipeline,
                "HealthPatrol": HealthPatrolPipeline,
                "HealthPatrolPipeline": HealthPatrolPipeline,
            }

            factory = pipeline_factories.get(pipeline_name)
            if not factory:
                raise ValueError(f"Unknown pipeline: {pipeline_name}")

            # Execute pipeline for each account, aggregate results
            all_step_results = []
            any_failed = False
            total_duration_ms = 0

            for account in accounts:
                logger.info(f"Schedule '{schedule_name}' running pipeline for account '{account.name}'")
                if factory is HealthPatrolPipeline:
                    pipeline = factory(account, config=config)
                else:
                    pipeline = factory(account)
                result = asyncio.run(pipeline.execute())
                total_duration_ms += result.duration_ms or 0
                for s in result.step_results:
                    all_step_results.append({
                        "account": account.name,
                        "name": s.step_name,
                        "status": s.status.value,
                        "data": s.data,
                    })
                if not result.success:
                    any_failed = True

            # Update execution record
            with get_db_session() as session:
                execution = session.query(ScheduleExecution).filter_by(
                    id=execution_id
                ).first()
                if execution:
                    execution.status = "failed" if any_failed else "completed"
                    execution.completed_at = datetime.utcnow()
                    execution.duration_ms = total_duration_ms
                    execution.result = {
                        "pipeline": pipeline_name,
                        "accounts": [a.name for a in accounts],
                        "steps": all_step_results,
                    }

            logger.info(f"Schedule '{schedule_name}' completed for {len(accounts)} account(s)")

            # Auto-notify on completion
            try:
                from agenticops.services.notification_service import notify_schedule_result
                notify_schedule_result(schedule_name, not any_failed)
            except Exception:
                logger.debug("Notification trigger failed", exc_info=True)

        except Exception as e:
            logger.error(f"Schedule '{schedule_name}' failed: {e}")

            with get_db_session() as session:
                execution = session.query(ScheduleExecution).filter_by(
                    id=execution_id
                ).first()
                if execution:
                    execution.status = "failed"
                    execution.completed_at = datetime.utcnow()
                    execution.error = str(e)

            # Auto-notify on failure
            try:
                from agenticops.services.notification_service import notify_schedule_result
                notify_schedule_result(schedule_name, False, str(e))
            except Exception:
                logger.debug("Notification trigger failed", exc_info=True)

    def _execute_agent_chain(self, schedule: Schedule, execution_id: int):
        """Execute an AgentChain schedule by sending a prompt to the Main Agent."""
        from agenticops.agents.main_agent import create_main_agent

        config = schedule.config or {}
        prompt = config.get("prompt", "")
        if not prompt:
            with get_db_session() as session:
                ex = session.query(ScheduleExecution).filter_by(id=execution_id).first()
                if ex:
                    ex.status = "failed"
                    ex.completed_at = datetime.utcnow()
                    ex.error = "AgentChain config missing required 'prompt' field"
            return

        skills = config.get("skills", [])
        report_type = config.get("report_type")
        notify_channels = config.get("notify_channels", [])
        timeout_seconds = config.get("timeout_seconds", 300)

        # Build enhanced prompt (notify_channels handled externally via share_content)
        parts = []
        if skills:
            parts.append(f"First activate these skills: {', '.join(skills)}.")
        parts.append(prompt)
        if report_type:
            parts.append(f"Generate a {report_type} type report.")
        enhanced_prompt = " ".join(parts)

        response_text = ""
        timed_out = False

        def _run():
            nonlocal response_text
            try:
                # Suppress auto report distribution during scheduled runs
                from agenticops.services.notification_service import set_schedule_running
                set_schedule_running(True)
                try:
                    agent = create_main_agent()
                    result = agent(enhanced_prompt)
                    response_text = str(result)
                finally:
                    set_schedule_running(False)
            except Exception as e:
                raise e

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            timed_out = True
            logger.warning(f"AgentChain '{schedule.name}' timed out after {timeout_seconds}s")

        # Upload content to S3 and get presigned URL for delivery
        presigned_url = None
        if response_text and not timed_out:
            try:
                from agenticops.storage.backend import get_storage_backend

                backend = get_storage_backend()
                ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                safe_name = "".join(
                    c if c.isalnum() or c in "-_" else "_"
                    for c in schedule.name[:50]
                )
                key = f"schedule-outputs/{ts}_{safe_name}.md"
                uri = backend.write(
                    key, response_text.encode("utf-8"), content_type="text/markdown"
                )
                presigned_url = backend.presigned_url(uri, expiry=72 * 3600)
            except Exception:
                logger.debug("Failed to upload schedule output to storage", exc_info=True)

        with get_db_session() as session:
            ex = session.query(ScheduleExecution).filter_by(id=execution_id).first()
            if ex:
                ex.completed_at = datetime.utcnow()
                ex.duration_ms = int((ex.completed_at - ex.started_at).total_seconds() * 1000)
                if timed_out:
                    ex.status = "failed"
                    ex.error = f"Timed out after {timeout_seconds}s"
                    ex.result = {"agent_output": response_text or "(partial)", "prompt": prompt}
                else:
                    result_data: Dict[str, Any] = {"agent_output": response_text, "prompt": prompt}
                    if presigned_url:
                        result_data["presigned_url"] = presigned_url
                    ex.status = "completed"
                    ex.result = result_data

        # Notify — include content summary + presigned URL for notify_channels
        try:
            from agenticops.services.notification_service import notify_schedule_result
            notify_schedule_result(schedule.name, not timed_out)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        # Deliver full content to configured notify_channels via share_content
        # (supports HTML email for html-preferred channels)
        if notify_channels and response_text and not timed_out:
            try:
                from agenticops.tools.notification_tools import share_content as _share

                _share(
                    subject=f"Schedule '{schedule.name}' — Output",
                    body=response_text,
                    channel_names=",".join(notify_channels),
                    upload_to_s3=True,
                )
                logger.info(
                    "Delivered schedule '%s' content to channels: %s",
                    schedule.name, notify_channels,
                )
            except Exception:
                logger.warning(
                    "Failed to deliver schedule '%s' content to channels",
                    schedule.name, exc_info=True,
                )

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

        # Load schedule data and close the session before executing
        with get_db_session() as session:
            schedule = session.query(Schedule).filter_by(name=name).first()
            if not schedule:
                return None
            schedule_id = schedule.id
            info = {
                "id": schedule.id,
                "name": schedule.name,
                "pipeline_name": schedule.pipeline_name,
                "account_name": schedule.account_name,
                "config": dict(schedule.config) if schedule.config else {},
            }

        # Execute outside any session
        scheduler = Scheduler()
        scheduler._execute_schedule_by_info(info)

        # Query the result in a fresh session
        with get_db_session() as session:
            return (
                session.query(ScheduleExecution)
                .filter_by(schedule_id=schedule_id)
                .order_by(ScheduleExecution.started_at.desc())
                .first()
            )
