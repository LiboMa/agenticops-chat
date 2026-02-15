# Phase 2a: RCA Agent MVP Design

**Status**: Approved
**Date**: 2025-02-14

## Overview

RCA Agent receives a HealthIssue ID, executes root cause analysis using AWS tools + Knowledge Base, and persists structured results via `save_rca_result`.

## File Changes

| File | Action | Summary |
|------|--------|---------|
| `models.py` | MODIFY | RCAResult FK Anomaly -> HealthIssue, new fields, migration |
| `metadata_tools.py` | MODIFY | Implement save_rca_result, add get_rca_result |
| `agents/rca_agent.py` | CREATE | @tool rca_agent following detect_agent pattern |
| `agents/main_agent.py` | MODIFY | Register rca_agent, update system prompt |
| `agents/__init__.py` | MODIFY | Export rca_agent |
| `tests/test_models.py` | MODIFY | RCAResult + HealthIssue relationship tests |
| `tests/test_rca_tools.py` | CREATE | save_rca_result / get_rca_result unit tests |

## Dependency Order

```
Batch 1: models.py
Batch 2: metadata_tools.py + rca_agent.py (parallel)
Batch 3: main_agent.py + __init__.py + tests (parallel)
```

## Key Decisions

- RCAResult.health_issue_id FK replaces anomaly_id
- init_db() detects old schema (anomaly_id column) and drops/recreates
- rca_agent follows detect_agent.py pattern exactly: @tool, BedrockModel, callback_handler=None
- System prompt enforces: read issue -> set investigating -> search SOP -> search cases -> CloudTrail -> metrics -> save_rca_result
