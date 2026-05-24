# Schedule & Task Agent Tools Design

> **Date**: 2026-05-24 | **Branch**: feature/self-improving-skills | **Priority**: P1 of 3

## Goal

Allow Agents to create, manage, and execute Schedule Jobs and one-shot tasks via Chat.
Users can use natural language or slash commands (`/run`, `/schedule`) to trigger.

## Architecture

Reuse existing `Schedule` model. One-shot tasks = Schedule with `cron_expression="@once"`.
5 Agent tools registered on Main Agent. 2 CLI slash commands as shortcuts.

## Data Model

Zero new tables. One-shot tasks use existing `Schedule`:

| Field | One-shot | Recurring |
|-------|----------|-----------|
| `cron_expression` | `"@once"` | Normal cron |
| `pipeline_name` | `"AgentChain"` | Any pipeline |
| `is_enabled` | Auto-disable after execution | Stays `True` |
| `config.prompt` | User's task description | AgentChain prompt |
| `config.report_format` | `markdown`/`html`/`json` | Same |
| `config.report_template` | Custom MD template or empty (use default) | Same |

## Agent Tools

File: `src/agenticops/tools/schedule_tools.py`

### run_task(prompt, report_format?, report_template?, notify_channels?)

Create `@once` Schedule and immediately execute. Returns execution status.

### create_schedule(name, prompt, cron, account_name?, report_format?, report_template?, notify_channels?)

Create recurring AgentChain Schedule. Agent parses cron from natural language.

### list_schedules(include_completed=False)

List all schedules. Optionally include completed one-shot tasks.

### manage_schedule(schedule_id, action)

Actions: `enable`, `disable`, `delete`, `run_now`.

### get_schedule_history(schedule_id, limit=10)

Return recent executions for a schedule.

## Report Template

When executing AgentChain, append report instructions to user prompt:

- If `config.report_template` is set: use user's custom template
- Otherwise: use default system template:

```
[REPORT INSTRUCTIONS]
- Output format: {report_format}
- Report type: {report_type or "general"}
- Save report to storage backend with timestamp filename
- Include: summary section, detailed findings, recommendations
- If notify_channels specified, use share_content to deliver
```

## Scheduler Changes

In `_check_schedules()`:
- Detect `@once` schedules (enabled, next_run_at=None) → mark as due immediately
- After execution completes: set `is_enabled=False`

In `run_task` tool: create record → call `Scheduler.run_schedule(id)` directly (no 60s wait).

## Slash Commands

Registered in `cli/main.py`:

- `/run <desc>` → send to Agent: "Execute this task immediately: {desc}"
- `/schedule <desc>` → send to Agent: "Create a recurring schedule for: {desc}"

Agent interprets natural language and calls the appropriate tool.

## Tool Registration

In `main_agent.py`, add schedule tools to Main Agent's tool list:
```python
from agenticops.tools.schedule_tools import (
    run_task, create_schedule, list_schedules, manage_schedule, get_schedule_history
)
```

## Scope Boundary (P1 only)

- P2 (Chat display): Agent formats tool results for chat presentation
- P3 (Frontend UI): Schedules page redesign with one-shot task section
