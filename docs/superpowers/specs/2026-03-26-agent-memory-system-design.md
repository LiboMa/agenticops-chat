# Agent Memory System Design

> Date: 2026-03-26
> Status: Draft
> Author: AgenticOps Team

## Problem

AgenticOps has 7 specialized agents (main, scan, detect, rca, sre, executor, reporter). Currently they are stateless across sessions — each invocation starts fresh with a fixed system prompt. This leads to recurring issues:

- **False positives**: detect agent repeatedly flags normal CPU fluctuations (e.g., t3.medium at 60%) as spikes
- **No learning**: user corrects an agent in chat, but next session the same mistake recurs
- **No cross-agent knowledge**: RCA agent doesn't know about detect's history of misclassifications
- **Lost operational context**: infrastructure baselines, team preferences, and past incident patterns are forgotten

## Solution

A **Markdown-based, per-agent memory system** with feedback-driven learning. Agents accumulate operational experience through user feedback and auto-learning, forming "operational intuition" while maintaining human control.

### Design Principles

1. **Human-readable**: Memories are Markdown files — reviewable, editable, git-trackable
2. **Per-agent scoping**: Each agent has its own memory space, with shared cross-agent access
3. **Feedback-driven**: Memories come from user correction, chat interaction, or auto-learning
4. **Token-efficient**: Capped injection with prompt caching; on-demand deep search via tool
5. **Simple state model**: active / archived (no numerical confidence scoring)

## Architecture

### Data Structure

```
config/agent-memory/
  detect/
    MEMORY.md                    # Index (one-line entries)
    cpu_spike_normal.md          # Individual memory
    rds_conn_fluctuation.md
  rca/
    MEMORY.md
    ec2_timeout_sg_pattern.md
  sre/
    MEMORY.md
  executor/
    MEMORY.md
  reporter/
    MEMORY.md
  scan/
    MEMORY.md
  shared/                        # Cross-agent shared memories
    MEMORY.md
    infra_baseline.md
```

### Memory File Format

Each memory file uses YAML frontmatter + Markdown body:

```markdown
---
agent: detect
type: feedback
status: active
source: user
resource_pattern: "EC2/t3.*"
related_issue_id: 42
created_at: 2026-03-26
last_confirmed: 2026-03-26
---

CPU utilization between 50-70% on t3.medium/t3.large instances is normal
operational fluctuation during business hours. Do NOT flag as CPU spike issue.

Confirmed by: user feedback on issue #42
```

### Frontmatter Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent` | string | Y | Agent name: detect, rca, sre, executor, reporter, scan, shared |
| `type` | string | Y | Memory type: feedback, pattern, preference, baseline |
| `status` | string | Y | active or archived |
| `source` | string | Y | Origin: user, chat, auto |
| `resource_pattern` | string | N | Resource match pattern (e.g., "EC2/t3.*") |
| `related_issue_id` | int | N | Associated HealthIssue ID |
| `created_at` | date | Y | Creation date |
| `last_confirmed` | date | N | Last positive confirmation date |

### MEMORY.md Index Format

Each agent's MEMORY.md is a one-line-per-entry index:

```markdown
# Detect Agent Memory

- [CPU spike normal](cpu_spike_normal.md) - t3.* CPU 50-70% is normal fluctuation
- [RDS conn fluctuation](rds_conn_fluctuation.md) - RDS connections < 80% is normal
```

## Feedback Mechanisms

### 1. UI Button Feedback (Primary)

Issue detail page gets two new buttons: "False Positive" and "Confirmed".

**Flow (False Positive):**

1. User clicks "False Positive" on Issue #42 (optional note text)
2. `POST /api/issues/{id}/feedback` `{type: "false_positive", note: "normal fluctuation"}`
3. Backend extracts pattern from issue (resource_type, metric, threshold)
4. Checks `config/agent-memory/detect/` for existing matching memory:
   - **Exists**: updates `last_confirmed` timestamp
   - **Not exists**: creates new `.md` file + updates `MEMORY.md` index
5. Issue status set to `dismissed`

**Flow (Confirmed):**

1. User clicks "Confirmed" on Issue #42
2. If a memory existed that tried to suppress this pattern, mark it `archived`
3. Issue remains in current status (no change)

### 2. Chat Natural Language Feedback

User says in chat: "This CPU alarm is a false positive, t3.medium at 60% is normal"

1. Main agent recognizes feedback intent
2. Calls `record_agent_feedback` tool with extracted pattern
3. Tool creates/updates memory file (same as UI path)
4. Agent confirms to user: "Recorded: CPU 60% on t3.medium is normal. Detect agent will remember this."

### 3. Auto-Learning

- Issue `dismissed` -> system creates memory with `source: auto`
- Issue `resolved` (actual fix applied) -> no feedback memory created (detection was correct)

## Memory Injection & Search

### Injection at Agent Startup

When an agent is created (session start or pipeline execution):

```python
def load_agent_memory(agent_name: str, max_entries: int = 10) -> str:
    """Load per-agent + shared memories, return formatted prompt context."""
    memories = []

    # 1. Agent's own memories (active only, sorted by last_confirmed desc)
    for md_file in agent_dir:
        if status == "active":
            memories.append(content)

    # 2. Shared memories
    for md_file in shared_dir:
        if status == "active":
            memories.append(content)

    # 3. Cap at max_entries
    memories = memories[:max_entries]

    return "[Agent Memory]\n" + "\n---\n".join(memories)
```

Injected into system prompt via `build_system_prompt()`:

```
[Preamble + Account]
[Base Agent Prompt]
[Agent Memory - learned from past feedback]   <-- NEW
[Skills Protocol]
```

### On-Demand Cross-Agent Search

New tool available to all agents:

```python
@tool
def search_agent_memory(query: str, agent_name: str = "") -> str:
    """Search agent memories by keyword.

    Args:
        query: Search keywords (e.g., "CPU spike", "RDS connection")
        agent_name: Filter by agent, or empty for all agents including shared
    """
```

### Search Strategy Summary

| Scenario | Method | Timing |
|----------|--------|--------|
| Agent startup | Full load per-agent + shared (max 10) | System prompt injection |
| Agent needs more context | Keyword search via `search_agent_memory` tool | During execution |
| User browses memories | `GET /api/agent-memory?agent=detect` | Settings page |

## Token Cost Analysis

| Component | Tokens | Notes |
|-----------|--------|-------|
| Single memory file | ~150-300 | 100-200 words |
| 10 memories injected | ~1,500-3,000 | Per agent |
| Current system prompt | ~2,000-5,000 | Existing preamble + instructions |
| **Total increase** | **~1,500-3,000** | ~1.5% of 200K context |

**Optimizations:**
- Max 10 entries injected; rest available via tool search
- Bedrock prompt caching enabled: memory section cached across consecutive calls
- Feedback extraction uses Haiku ($0.25/1M input tokens)

**Estimated cost**: ~$0.06/session at Sonnet pricing; near zero with cache hits.

## API Endpoints

### New Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/issues/{id}/feedback` | Record user feedback on an issue |
| `GET` | `/api/agent-memory` | List memories (filter by agent, type, status) |
| `GET` | `/api/agent-memory/{agent}/{filename}` | Read single memory file |
| `PUT` | `/api/agent-memory/{agent}/{filename}` | Update memory file |
| `DELETE` | `/api/agent-memory/{agent}/{filename}` | Archive/delete memory |

### Request/Response Examples

**POST /api/issues/42/feedback**
```json
{
  "type": "false_positive",
  "note": "Normal CPU fluctuation during business hours"
}
```

**GET /api/agent-memory?agent=detect&status=active**
```json
[
  {
    "agent": "detect",
    "filename": "cpu_spike_normal.md",
    "type": "feedback",
    "status": "active",
    "source": "user",
    "summary": "t3.* CPU 50-70% is normal fluctuation",
    "created_at": "2026-03-26",
    "last_confirmed": "2026-03-26"
  }
]
```

## Implementation Phases

### Phase 1: Core Framework

**Goal**: Memory files + injection + tools. Agents can learn from chat feedback.

| Action | File | Description |
|--------|------|-------------|
| Create | `src/agenticops/memory/agent_memory.py` | `load_agent_memory()`, `save_feedback()`, `search_memories()`, `parse_frontmatter()` |
| Create | `src/agenticops/tools/memory_tools.py` | `record_agent_feedback` + `search_agent_memory` @tool functions |
| Create | `config/agent-memory/` directory tree | 7 agent dirs + shared/, each with MEMORY.md |
| Modify | `src/agenticops/agents/preamble.py` | Inject `load_agent_memory(agent_name)` in `build_system_prompt()` |
| Modify | 7 agent files | Register `search_agent_memory` tool; main_agent also gets `record_agent_feedback` |
| Create | `tests/test_agent_memory.py` | Unit tests for load, save, search, parse |

### Phase 2: UI Feedback

**Goal**: Issue detail page gets feedback buttons; Settings page shows memory management.

| Action | File | Description |
|--------|------|-------------|
| Add API | `src/agenticops/web/app.py` | `POST /api/issues/{id}/feedback` + `GET/PUT/DELETE /api/agent-memory` |
| Modify | `IssueActionBar.tsx` | "False Positive" / "Confirmed" buttons |
| Modify | `Settings.tsx` | "Agent Memory" card: list, view, delete memories per agent |
| Create | `src/agenticops/web/frontend/src/hooks/useAgentMemory.ts` | React Query hook |

### Phase 3: Auto-Learning & Suppression

**Goal**: System learns from issue lifecycle; agents log suppressions.

| Action | File | Description |
|--------|------|-------------|
| Modify | `services/pipeline_events.py` | On issue dismissed: auto-create feedback memory (source: auto) |
| Modify | detect agent prompt | Instruction: match memory patterns, log suppression instead of creating issue |
| Add API | `app.py` | `GET /api/agent-memory/suppression-log` |
| Frontend | New UI section | "Suppressed Detections" list with confirm/reject actions |

## Evolution Taxonomy

This system enables three levels of agent evolution:

| Level | Type | Human Role | Example |
|-------|------|------------|---------|
| L1: Feedback Learning | Human teaches agent | Active (click/chat) | "CPU 60% is normal" |
| L2: Auto-Learning | Agent learns from outcomes | Passive (issue state changes) | dismissed = likely false positive |
| L3: Cross-Agent Propagation | Agent teaches agent | None | detect's false positive data available to RCA |

**Future L4** (not in scope): Agent automatically creates new Skills from accumulated patterns.

## Files Changed (Total)

| Phase | New Files | Modified Files | Estimated LOC |
|-------|-----------|----------------|---------------|
| Phase 1 | 3 (agent_memory.py, memory_tools.py, tests) + directory tree | 8 (preamble + 7 agents) | ~400 |
| Phase 2 | 1 (useAgentMemory.ts) | 3 (app.py, IssueActionBar, Settings) | ~300 |
| Phase 3 | 0 | 3 (pipeline_events, detect prompt, app.py) | ~150 |
| **Total** | **4 new files** | **14 modified files** | **~850 LOC** |
