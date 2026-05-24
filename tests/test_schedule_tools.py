"""Tests for schedule tools (Agent-facing task/schedule management)."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


def test_build_enhanced_prompt_default_template():
    """When no custom template, uses default report instructions."""
    from agenticops.tools.schedule_tools import build_enhanced_prompt

    config = {"prompt": "Check RDS backup status", "report_format": "markdown", "report_type": "daily"}
    result = build_enhanced_prompt(config)

    assert "Check RDS backup status" in result
    assert "[REPORT INSTRUCTIONS]" in result
    assert "markdown" in result
    assert "daily" in result


def test_build_enhanced_prompt_custom_template():
    """When custom template is provided, uses it instead of default."""
    from agenticops.tools.schedule_tools import build_enhanced_prompt

    config = {
        "prompt": "Check RDS backup status",
        "report_format": "markdown",
        "report_template": "## Summary\n## Findings\n## Recommendations",
    }
    result = build_enhanced_prompt(config)

    assert "Check RDS backup status" in result
    assert "## Summary" in result
    assert "[REPORT INSTRUCTIONS]" not in result


def test_run_task_creates_once_schedule(tmp_path):
    """run_task creates a @once Schedule and triggers execution."""
    from agenticops.tools.schedule_tools import run_task

    mock_schedule = MagicMock()
    mock_schedule.id = 42

    with patch("agenticops.tools.schedule_tools.get_db_session") as mock_db, \
         patch("agenticops.tools.schedule_tools._trigger_run_now") as mock_trigger:
        # Mock the session context
        session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        session.flush = MagicMock()

        # Make session.add capture the schedule object to get its id
        def capture_add(obj):
            obj.id = 42
        session.add = capture_add

        result = run_task._tool_func(prompt="Check S3 public access")

    assert "42" in result
    assert "task-" in result


def test_create_schedule_validates_cron():
    """create_schedule rejects invalid cron expressions."""
    from agenticops.tools.schedule_tools import create_schedule

    with patch("agenticops.tools.schedule_tools.get_db_session"):
        result = create_schedule._tool_func(
            name="test", prompt="test", cron="invalid-cron"
        )

    assert "Invalid cron" in result


def test_create_schedule_success():
    """create_schedule creates a recurring schedule."""
    from agenticops.tools.schedule_tools import create_schedule

    with patch("agenticops.tools.schedule_tools.get_db_session") as mock_db:
        session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.flush = MagicMock()

        def capture_add(obj):
            obj.id = 1
        session.add = capture_add

        result = create_schedule._tool_func(
            name="daily-rds-check",
            prompt="Check RDS backup status",
            cron="0 8 * * *",
        )

    assert "daily-rds-check" in result
    assert "0 8 * * *" in result
    assert "created" in result.lower()


def test_list_schedules_empty():
    """list_schedules returns message when no schedules."""
    from agenticops.tools.schedule_tools import list_schedules

    with patch("agenticops.tools.schedule_tools.get_db_session") as mock_db:
        session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        query = MagicMock()
        session.query.return_value.order_by.return_value = query
        query.filter.return_value.all.return_value = []

        result = list_schedules._tool_func()

    assert "No schedules" in result


def test_manage_schedule_invalid_action():
    """manage_schedule rejects invalid actions."""
    from agenticops.tools.schedule_tools import manage_schedule

    result = manage_schedule._tool_func(schedule_id=1, action="restart")
    assert "Invalid action" in result


def test_skills_protocol_mentions_schedules():
    """Main agent system prompt mentions schedule tools."""
    from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT

    assert "run_task" in MAIN_SYSTEM_PROMPT
    assert "create_schedule" in MAIN_SYSTEM_PROMPT
