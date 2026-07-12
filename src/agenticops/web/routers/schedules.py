"""Schedule API endpoints — extracted from app.py (no logic change)."""

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from agenticops.config import settings
from agenticops.models import get_db_session
from agenticops.web.schemas import (
    ScheduleCreate,
    ScheduleExecutionResponse,
    ScheduleResponse,
    ScheduleUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/schedules", response_model=List[ScheduleResponse])
async def api_list_schedules():
    """List all schedules."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedules = session.query(Schedule).order_by(Schedule.created_at.desc()).all()
        return [ScheduleResponse.model_validate(s) for s in schedules]


@router.get("/api/schedules/pipeline-options")
async def api_pipeline_options():
    """Return available pipeline names and AgentChain config schema."""
    return {
        "pipelines": ["FullScan", "Monitoring", "DailyReport", "HealthPatrol", "GalaxyBuild", "AgentChain"],
        "agent_chain_config": {
            "prompt": {"type": "string", "required": True, "description": "Task description for the agent"},
            "skills": {"type": "array", "required": False, "description": "Skills to activate"},
            "report_type": {"type": "string", "required": False, "enum": ["daily", "incident", "inventory"]},
            "notify_channels": {"type": "array", "required": False, "description": "Notification channels"},
            "timeout_seconds": {"type": "integer", "required": False, "default": 300},
        },
    }


@router.get("/api/schedules/cron-preview")
async def api_cron_preview(expr: str = ""):
    """Validate a cron expression and return the next 3 run times."""
    from agenticops.scheduler.scheduler import CronParser

    if not expr.strip():
        return {"valid": False, "error": "Empty expression"}
    try:
        parser = CronParser(expr.strip())
        now = datetime.now(timezone.utc)
        runs = []
        t = now
        for _ in range(3):
            t = parser.next_run(t)
            runs.append(t.isoformat())
        return {"valid": True, "next_runs": runs}
    except (ValueError, Exception) as e:
        return {"valid": False, "error": str(e)}


@router.get("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def api_get_schedule(schedule_id: int):
    """Get schedule by ID."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleResponse.model_validate(schedule)


@router.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
async def api_create_schedule(data: ScheduleCreate):
    """Create a new schedule."""
    from agenticops.scheduler.scheduler import Schedule, CronParser

    # Validate cron expression
    try:
        CronParser(data.cron_expression)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

    with get_db_session() as session:
        existing = session.query(Schedule).filter_by(name=data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Schedule name already exists")

        schedule = Schedule(
            name=data.name,
            pipeline_name=data.pipeline_name,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            account_name=data.account_name,
            is_enabled=data.is_enabled,
            max_retries=data.max_retries,
            config=data.config,
        )
        session.add(schedule)
        session.flush()
        return ScheduleResponse.model_validate(schedule)


@router.put("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
async def api_update_schedule(schedule_id: int, data: ScheduleUpdate):
    """Update a schedule."""
    from agenticops.scheduler.scheduler import Schedule, CronParser

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        update_data = data.model_dump(exclude_unset=True)

        # Validate cron if being updated
        if "cron_expression" in update_data:
            try:
                CronParser(update_data["cron_expression"])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

        for key, value in update_data.items():
            setattr(schedule, key, value)

        session.flush()
        return ScheduleResponse.model_validate(schedule)


@router.delete("/api/schedules/{schedule_id}", status_code=204)
async def api_delete_schedule(schedule_id: int):
    """Delete a schedule."""
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        session.delete(schedule)


@router.post("/api/schedules/{schedule_id}/run", status_code=202)
async def api_run_schedule(schedule_id: int, background_tasks: BackgroundTasks):
    """Run a schedule immediately in the background."""
    from agenticops.scheduler.scheduler import Schedule, Scheduler

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        schedule_name = schedule.name
        schedule.last_run_at = datetime.now(timezone.utc)

    def _run_in_background():
        try:
            Scheduler().run_now(schedule_name)
        except Exception as e:
            logger.error(f"Background run_now failed for schedule {schedule_name}: {e}")

    background_tasks.add_task(_run_in_background)
    return {"schedule_id": schedule_id, "status": "accepted"}


@router.get("/api/schedules/{schedule_id}/executions", response_model=List[ScheduleExecutionResponse])
async def api_list_schedule_executions(
    schedule_id: int,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
):
    """List execution history for a schedule."""
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        executions = (
            session.query(ScheduleExecution)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleExecution.started_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [ScheduleExecutionResponse.model_validate(e) for e in executions]
