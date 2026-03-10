# Phase 2b: Reporter Agent

## Overview

The Reporter Agent completes the operations pipeline: **scan -> detect -> rca -> report**. It gathers health issues, RCA results, and resource inventory to produce structured markdown reports, persisted to both the database and the filesystem.

## Architecture

```
Main Agent (orchestrator)
  └── reporter_agent @tool
        ├── metadata_tools: get_active_account, get_managed_resources,
        │                   get_health_issue, get_rca_result, list_health_issues
        ├── report_tools:   save_report, list_reports
        └── kb_tools:       search_similar_cases, write_kb_case
```

### Pattern

Follows the same **agents-as-tools** pattern as detect_agent and rca_agent:
- `@tool def reporter_agent(report_type, scope) -> str`
- Creates an inner `strands.Agent` with its own system prompt and tool set
- Returns a string summary to the orchestrator

## Report Types

| Type | Trigger | Content |
|------|---------|---------|
| `daily` | "daily report", "summary" | All issues + RCA summaries + inventory overview |
| `incident` | "incident report" | Critical/high issues with full RCA detail |
| `inventory` | "inventory report" | Resource inventory cross-referenced with issues |

## New Files

### `src/agenticops/tools/report_tools.py`

Two `@tool` functions:

- **`save_report(report_type, title, summary, content_markdown, report_metadata)`**
  - Validates report_type against `{daily, incident, inventory}`
  - Writes `.md` file to `settings.reports_dir` with timestamped filename
  - Creates `Report` DB row with file_path reference
  - Rolls back file on DB error

- **`list_reports(report_type, limit)`**
  - Queries `Report` table ordered by `created_at desc`
  - Optional type filter, capped at 100 results
  - Returns JSON array

### `src/agenticops/agents/reporter_agent.py`

- System prompt enforces a strict protocol: gather -> format -> save -> optionally write KB case
- Tools: metadata queries (read-only) + save_report + list_reports + KB tools
- Severity formatting uses emoji indicators for report readability

## Modified Files

### `src/agenticops/agents/main_agent.py`

- Added `reporter_agent` import and tool registration
- Added dispatch rule #9 for report/summary/daily report keywords
- Removed `COMING SOON` section (all pipeline agents now complete)

### `src/agenticops/agents/__init__.py`

- Added `reporter_agent` export

## Data Model

Uses the existing `Report` model (`models.py:337-350`):

```python
class Report(Base):
    __tablename__ = "reports"
    id, report_type, title, summary, content_markdown,
    content_html, file_path, report_metadata, created_at
```

No schema changes required.

## Testing

`tests/test_report_tools.py` covers:
- Basic save + DB verification
- File creation on disk
- Custom metadata persistence
- Invalid report_type rejection
- Invalid JSON metadata fallback
- Title truncation at 200 chars
- List: empty, all, filtered, limit, field presence

## Verification

```bash
python3 -m py_compile src/agenticops/tools/report_tools.py
python3 -m py_compile src/agenticops/agents/reporter_agent.py
python3 -m py_compile src/agenticops/agents/main_agent.py
python3 -m py_compile src/agenticops/agents/__init__.py
uv run pytest tests/test_report_tools.py -v
```
