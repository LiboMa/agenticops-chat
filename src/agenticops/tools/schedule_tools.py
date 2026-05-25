"""Schedule tools — Agent-facing tools for task and schedule management.

Allows agents to create one-shot tasks, recurring schedules, and manage
existing schedules via natural language in Chat.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from strands import tool

from agenticops.models import get_db_session

logger = logging.getLogger(__name__)

# Default report instructions appended when no custom template is given
_DEFAULT_REPORT_TEMPLATE = """
[REPORT INSTRUCTIONS]
- Output format: {report_format}
- Report type: {report_type}
- Save report to storage backend with timestamp filename
- Include: summary section, detailed findings, recommendations
- If notify_channels specified, use share_content to deliver
""".strip()


@tool
def run_task(
    prompt: str,
    report_format: str = "markdown",
    report_template: str = "",
    notify_channels: str = "",
) -> str:
    """Execute a one-shot task immediately via the AgentChain pipeline.

    Creates a Schedule record with @once and triggers immediate execution.
    The task runs once then auto-disables.

    Args:
        prompt: Natural language description of the task to execute.
        report_format: Output format — 'markdown', 'html', or 'json'. Default 'markdown'.
        report_template: Custom Markdown template for the report. Leave empty for default.
        notify_channels: Comma-separated notification channels (e.g., 'email,slack'). Empty = no notification.

    Returns:
        Task creation confirmation with execution ID and status.
    """
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution, Scheduler

    channels = [c.strip() for c in notify_channels.split(",") if c.strip()] if notify_channels else []

    config = {
        "prompt": prompt,
        "report_format": report_format,
        "report_template": report_template,
        "notify_channels": channels,
        "report_type": "general",
    }

    # Create @once schedule record
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    schedule_name = f"task-{ts}"

    with get_db_session() as session:
        schedule = Schedule(
            name=schedule_name,
            pipeline_name="AgentChain",
            schedule_type="one_time",
            cron_expression="@once",
            is_enabled=True,
            config=config,
        )
        session.add(schedule)
        session.flush()
        schedule_id = schedule.id
        session.expunge(schedule)

    # Trigger immediate execution
    try:
        scheduler = Scheduler()
        scheduler.run_schedule(schedule_id)
    except AttributeError:
        # Fallback: use the API trigger path
        _trigger_run_now(schedule_id)

    return (
        f"Task created and executing (ID: {schedule_id}).\n"
        f"Name: {schedule_name}\n"
        f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
        f"Use get_schedule_history(schedule_id={schedule_id}) to check results."
    )


@tool
def create_schedule(
    name: str,
    prompt: str,
    cron: str,
    account_name: str = "",
    report_format: str = "markdown",
    report_template: str = "",
    report_type: str = "",
    notify_channels: str = "",
) -> str:
    """Create a recurring scheduled task (AgentChain pipeline).

    The schedule runs on the specified cron expression, executing the prompt
    via the Main Agent each time.

    Args:
        name: Human-readable schedule name (unique, e.g., 'daily-rds-backup-check').
        prompt: Task description for the agent to execute each run.
        cron: Cron expression (5-field: minute hour day-of-month month day-of-week).
        account_name: Cloud account to operate on. Empty = all accounts.
        report_format: Output format — 'markdown', 'html', or 'json'. Default 'markdown'.
        report_template: Custom Markdown template. Empty = use default.
        report_type: Report type — 'daily', 'incident', 'inventory', or empty.
        notify_channels: Comma-separated channels. Empty = no notification.

    Returns:
        Schedule creation confirmation with ID and next run time.
    """
    from agenticops.scheduler.scheduler import Schedule, CronParser

    # Validate cron expression
    try:
        parser = CronParser(cron)
        next_run = parser.next_run(datetime.utcnow())
    except (ValueError, Exception) as e:
        return f"Invalid cron expression '{cron}': {e}"

    channels = [c.strip() for c in notify_channels.split(",") if c.strip()] if notify_channels else []

    config = {
        "prompt": prompt,
        "report_format": report_format,
        "report_template": report_template,
        "report_type": report_type,
        "notify_channels": channels,
    }

    with get_db_session() as session:
        # Check name uniqueness
        existing = session.query(Schedule).filter_by(name=name).first()
        if existing:
            return f"Schedule '{name}' already exists (ID: {existing.id}). Use a different name or manage_schedule to modify."

        schedule = Schedule(
            name=name,
            pipeline_name="AgentChain",
            schedule_type="recurring",
            cron_expression=cron,
            account_name=account_name or None,
            is_enabled=True,
            config=config,
            next_run_at=next_run,
        )
        session.add(schedule)
        session.flush()
        schedule_id = schedule.id

    return (
        f"Schedule created successfully.\n"
        f"ID: {schedule_id}\n"
        f"Name: {name}\n"
        f"Cron: {cron}\n"
        f"Next run: {next_run.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
    )


@tool
def list_schedules(include_completed: bool = False) -> str:
    """List all schedules and one-shot tasks.

    Args:
        include_completed: If True, include completed/disabled one-shot tasks. Default False.

    Returns:
        Formatted list of schedules with status, cron, and last/next run times.
    """
    from agenticops.scheduler.scheduler import Schedule

    with get_db_session() as session:
        query = session.query(Schedule).order_by(Schedule.created_at.desc())
        if not include_completed:
            query = query.filter(
                (Schedule.is_enabled == True) | (Schedule.cron_expression != "@once")  # noqa: E712
            )
        schedules = query.all()

    if not schedules:
        return "No schedules found."

    lines = [f"Schedules ({len(schedules)}):"]
    for s in schedules:
        status = "enabled" if s.is_enabled else "disabled"
        stype = "one-time" if (s.schedule_type == "one_time" or s.cron_expression == "@once") else f"cron: {s.cron_expression}"
        prompt_preview = (s.config or {}).get("prompt", "")[:60]
        lines.append(
            f"\n  [{s.id}] {s.name} ({status})"
            f"\n    Type: {stype} | Pipeline: {s.pipeline_name}"
            f"\n    Prompt: {prompt_preview}{'...' if len((s.config or {}).get('prompt', '')) > 60 else ''}"
            f"\n    Last run: {s.last_run_at.strftime('%Y-%m-%d %H:%M') if s.last_run_at else 'never'}"
            f"\n    Next run: {s.next_run_at.strftime('%Y-%m-%d %H:%M') if s.next_run_at else 'N/A'}"
        )

    return "\n".join(lines)


@tool
def manage_schedule(schedule_id: int, action: str) -> str:
    """Manage an existing schedule (enable, disable, delete, or run now).

    Args:
        schedule_id: ID of the schedule to manage.
        action: One of 'enable', 'disable', 'delete', 'run_now'.

    Returns:
        Confirmation of the action taken.
    """
    from agenticops.scheduler.scheduler import Schedule

    valid_actions = {"enable", "disable", "delete", "run_now"}
    if action not in valid_actions:
        return f"Invalid action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}"

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            return f"Schedule ID {schedule_id} not found."

        name = schedule.name

        if action == "enable":
            schedule.is_enabled = True
            return f"Schedule '{name}' (ID: {schedule_id}) enabled."

        elif action == "disable":
            schedule.is_enabled = False
            return f"Schedule '{name}' (ID: {schedule_id}) disabled."

        elif action == "delete":
            session.delete(schedule)
            return f"Schedule '{name}' (ID: {schedule_id}) deleted."

        elif action == "run_now":
            sid = schedule.id
            session.expunge(schedule)

    # run_now: trigger outside the session
    if action == "run_now":
        _trigger_run_now(sid)
        return f"Schedule '{name}' (ID: {schedule_id}) triggered for immediate execution."

    return "Done."


@tool
def get_schedule_history(schedule_id: int, limit: int = 10) -> str:
    """Get recent execution history for a schedule.

    Args:
        schedule_id: ID of the schedule.
        limit: Maximum number of executions to return. Default 10.

    Returns:
        Formatted execution history with status, duration, and results.
    """
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            return f"Schedule ID {schedule_id} not found."

        executions = (
            session.query(ScheduleExecution)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleExecution.started_at.desc())
            .limit(limit)
            .all()
        )

        if not executions:
            return f"No executions yet for schedule '{schedule.name}' (ID: {schedule_id})."

        lines = [f"Execution history for '{schedule.name}' (last {len(executions)}):"]
        for ex in executions:
            duration = f"{ex.duration_ms}ms" if ex.duration_ms else "running"
            result_preview = ""
            if ex.result:
                text = ex.result.get("response_text", ex.result.get("summary", ""))
                if text:
                    result_preview = f"\n    Result: {text[:120]}{'...' if len(text) > 120 else ''}"
            error_info = f"\n    Error: {ex.error[:100]}" if ex.error else ""

            lines.append(
                f"\n  [{ex.id}] {ex.status} | {ex.started_at.strftime('%Y-%m-%d %H:%M')}"
                f" | Duration: {duration}"
                f"{result_preview}{error_info}"
            )

        return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────


def _trigger_run_now(schedule_id: int) -> None:
    """Trigger immediate execution of a schedule via the Scheduler."""
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution, Scheduler

    with get_db_session() as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).first()
        if not schedule:
            return
        session.expunge(schedule)

    # Use a temporary Scheduler instance to execute
    scheduler = Scheduler()
    scheduler._execute_schedule(schedule)


def build_enhanced_prompt(config: dict) -> str:
    """Build the final prompt with report instructions appended.

    Called by the Scheduler's AgentChain executor to enhance the raw prompt.

    Args:
        config: Schedule config dict containing prompt, report_format, etc.

    Returns:
        Enhanced prompt string with report instructions.
    """
    prompt = config.get("prompt", "")
    report_template = config.get("report_template", "")
    report_format = config.get("report_format", "markdown")
    report_type = config.get("report_type", "general")

    if report_template:
        return f"{prompt}\n\n{report_template}"

    # Use default template
    instructions = _DEFAULT_REPORT_TEMPLATE.format(
        report_format=report_format,
        report_type=report_type or "general",
    )
    return f"{prompt}\n\n{instructions}"
