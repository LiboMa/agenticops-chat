# Agent Memory System Design

> Date: 2026-03-26
> Status: Approved
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
5. **Confidence-scored**: User-provided 1-5 confidence score determines injection priority

### Architectural Positioning

Agent Memory is a **behavioral constraint and enhancement layer**, distinct from existing DB-based case memory:

```
静态指令层:  system prompt + preamble + SKILL.md     (开发者写)
动态指令层:  agent-memory/*.md                        (反馈驱动，运行时演化)
数据记忆层:  DB agent_memory_facts / agent_memories   (case 经验)
```

| Layer | Purpose | Storage | Source |
|-------|---------|---------|--------|
| Agent Memory (new) | Constrain & enhance agent behavior | Markdown files | User feedback + auto-learning |
| MemoryService (existing, unchanged) | Remember case experiences | SQLite/PostgreSQL | Automatic LLM extraction |

These two systems coexist, serving different purposes. Agent Memory does NOT replace MemoryService.

## Architecture

### Data Structure

```
agent-memory/                        # Root level, parallel to skills/
  detect/
    MEMORY.md                        # Index (one-line entries)
    cpu_spike_normal.md              # Individual memory
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
  shared/                            # Cross-agent shared memories
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
confidence: 4
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
| `confidence` | int | Y | User-provided score 1-5 (default 3). Determines injection priority |
| `source` | string | Y | Origin: user, chat, auto |
| `resource_pattern` | string | N | Resource match pattern (e.g., "EC2/t3.*") |
| `related_issue_id` | int | N | Associated HealthIssue ID |
| `created_at` | date | Y | Creation date |
| `last_confirmed` | date | N | Last positive confirmation date |

### Confidence Scale

| Score | Meaning | Injection behavior |
|-------|---------|-------------------|
| 5 | Confirmed multiple times, certain | Always injected (top priority) |
| 4 | High confidence | Injected when within cap |
| 3 | Default for new memories | Injected when within cap |
| 2 | Uncertain, needs observation | Injected only if space remains |
| 1 | Questionable, possibly outdated | Rarely injected, available via search |

### MEMORY.md Index Format

Each agent's MEMORY.md is a one-line-per-entry index:

```markdown
# Detect Agent Memory

- [CPU spike normal](cpu_spike_normal.md) — t3.* CPU 50-70% is normal fluctuation [confidence: 4]
- [RDS conn fluctuation](rds_conn_fluctuation.md) — RDS connections < 80% is normal [confidence: 3]
```

## Feedback Mechanisms

### 1. UI Button Feedback (Primary)

Issue detail page gets two new buttons: "False Positive" and "Confirmed".

**Flow (False Positive):**

1. User clicks "False Positive" on Issue #42
2. Optional: note text + confidence score (1-5 star rating, default 3)
3. `POST /api/issues/{id}/feedback` `{type: "false_positive", note: "...", confidence: 4}`
4. Backend extracts pattern from issue (resource_type, metric, threshold)
5. Checks `agent-memory/detect/` for existing matching memory:
   - **Exists**: updates `last_confirmed` timestamp + confidence (if provided)
   - **Not exists**: creates new `.md` file + updates `MEMORY.md` index
6. Issue status set to `dismissed`

**Flow (Confirmed):**

1. User clicks "Confirmed" on Issue #42
2. If a memory existed that tried to suppress this pattern, mark it `archived`
3. Issue remains in current status (no change)

### 2. Chat Natural Language Feedback

User says in chat: "This CPU alarm is a false positive, t3.medium at 60% is normal, confidence 5"

1. Main agent recognizes feedback intent
2. Calls `record_agent_feedback` tool with extracted pattern and confidence
3. Tool creates/updates memory file (same as UI path)
4. **Hot-reload**: updates current session agent's system prompt immediately
5. Agent confirms to user: "Recorded: CPU 60% on t3.medium is normal (confidence: 5). Detect agent will remember this."

### 3. Auto-Learning

- Issue `dismissed` → system creates memory with `source: auto`, `confidence: 2`
- Issue `resolved` (actual fix applied) → no feedback memory created (detection was correct)

### 4. Settings Page Manual Scoring

- Settings "Agent Memory" card shows all memories per agent
- Each memory has an editable confidence score (1-5)
- `PUT /api/agent-memory/{agent}/{filename}` to update

## Real-time Memory Update

### Write Path

```
User feedback (Chat/UI/Settings)
      │
      ▼
  Write .md file ─────────── Persistent (milliseconds)
      │
      ├──▶ Hot-reload current main_agent.system_prompt ── This session, immediate
      │
      ├──▶ Sub-agents pick up on next invocation ── Near-real-time (seconds)
      │    (sub-agents are created fresh per @tool call)
      │
      └──▶ All future sessions inject at startup ── Permanent
```

### Hot-reload Mechanism

After writing a memory file, the `record_agent_feedback` tool rebuilds the memory prompt section and patches the live agent:

```python
def record_agent_feedback(...):
    # 1. Write .md file
    save_memory_file(agent_name, filename, content)
    update_memory_index(agent_name)

    # 2. Hot-reload current session agent's system prompt
    if current_agent:
        memory_block = load_agent_memory(agent_name)
        current_agent.system_prompt = rebuild_prompt_with_memory(
            current_agent.system_prompt, memory_block
        )
```

Sub-agents (detect, rca, etc.) are `@tool` functions that create a fresh `Agent` instance per call — they automatically pick up new memories on next invocation via `build_system_prompt()`.

## Memory Injection & Search

### Injection at Agent Startup

When an agent is created (session start or pipeline execution):

```python
def load_agent_memory(agent_name: str, max_entries: int = 10) -> str:
    """Load per-agent + shared memories, return formatted prompt context."""
    memories = []

    # 1. Agent's own memories (active only)
    for md_file in agent_dir:
        if status == "active":
            memories.append(parsed)

    # 2. Shared memories
    for md_file in shared_dir:
        if status == "active":
            memories.append(parsed)

    # 3. Sort by confidence (high first), cap at max_entries
    memories.sort(key=lambda m: m["confidence"], reverse=True)
    memories = memories[:max_entries]

    return "[Agent Memory]\n" + "\n---\n".join(m["body"] for m in memories)
```

Injected into system prompt via `build_system_prompt()`:

```
[Preamble + Account]
[Base Agent Prompt]
[Agent Memory - learned from past feedback]   <-- NEW
[Output Rules]
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
| Agent startup | Full load per-agent + shared (max 10, sorted by confidence) | System prompt injection |
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
- Confidence sorting ensures highest-value memories use the budget
- Bedrock prompt caching enabled: memory section cached across consecutive calls
- Feedback extraction uses Haiku ($0.25/1M input tokens)

**Estimated cost**: ~$0.06/session at Sonnet pricing; near zero with cache hits.

## API Endpoints

### New Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/issues/{id}/feedback` | Record user feedback on an issue (with optional confidence) |
| `GET` | `/api/agent-memory` | List memories (filter by agent, type, status) |
| `GET` | `/api/agent-memory/{agent}/{filename}` | Read single memory file |
| `PUT` | `/api/agent-memory/{agent}/{filename}` | Update memory file (including confidence) |
| `DELETE` | `/api/agent-memory/{agent}/{filename}` | Archive/delete memory |

### Request/Response Examples

**POST /api/issues/42/feedback**
```json
{
  "type": "false_positive",
  "note": "Normal CPU fluctuation during business hours",
  "confidence": 4
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
    "confidence": 4,
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
| Create | `src/agenticops/memory/agent_memory.py` | `load_agent_memory()`, `save_feedback()`, `search_memories()`, `parse_frontmatter()`, `rebuild_prompt_with_memory()` |
| Create | `src/agenticops/tools/memory_tools.py` | `record_agent_feedback` + `search_agent_memory` @tool functions |
| Create | `agent-memory/` directory tree | 7 agent dirs + shared/, each with MEMORY.md |
| Modify | `src/agenticops/agents/preamble.py` | Inject `load_agent_memory(agent_name)` in `build_system_prompt()` |
| Modify | 7 agent files | Register `search_agent_memory` tool; main_agent also gets `record_agent_feedback` |
| Create | `tests/test_agent_memory.py` | Unit tests for load, save, search, parse, confidence sorting |

### Phase 2: UI Feedback

**Goal**: Issue detail page gets feedback buttons; Settings page shows memory management with confidence scoring.

| Action | File | Description |
|--------|------|-------------|
| Add API | `src/agenticops/web/app.py` | `POST /api/issues/{id}/feedback` + `GET/PUT/DELETE /api/agent-memory` |
| Modify | `IssueActionBar.tsx` | "False Positive" / "Confirmed" buttons with optional confidence stars |
| Modify | `Settings.tsx` | "Agent Memory" card: list, view, delete, edit confidence per agent |
| Create | `src/agenticops/web/frontend/src/hooks/useAgentMemory.ts` | React Query hook |

### Phase 3: Auto-Learning & Suppression

**Goal**: System learns from issue lifecycle; agents log suppressions.

| Action | File | Description |
|--------|------|-------------|
| Modify | `services/pipeline_events.py` | On issue dismissed: auto-create feedback memory (source: auto, confidence: 2) |
| Modify | detect agent prompt | Instruction: match memory patterns, log suppression instead of creating issue |
| Add API | `app.py` | `GET /api/agent-memory/suppression-log` |
| Frontend | New UI section | "Suppressed Detections" list with confirm/reject actions |

## Evolution Taxonomy

This system enables three levels of agent evolution:

| Level | Type | Human Role | Example |
|-------|------|------------|---------|
| L1: Feedback Learning | Human teaches agent | Active (click/chat + confidence score) | "CPU 60% is normal" (confidence: 5) |
| L2: Auto-Learning | Agent learns from outcomes | Passive (issue state changes) | dismissed = likely false positive (confidence: 2) |
| L3: Cross-Agent Propagation | Agent teaches agent | None | detect's false positive data available to RCA via shared/ |

**Future L4** (not in scope): Agent automatically creates new Skills from accumulated patterns.

## Files Changed (Total)

| Phase | New Files | Modified Files | Estimated LOC |
|-------|-----------|----------------|---------------|
| Phase 1 | 3 (agent_memory.py, memory_tools.py, tests) + directory tree | 8 (preamble + 7 agents) | ~450 |
| Phase 2 | 1 (useAgentMemory.ts) | 3 (app.py, IssueActionBar, Settings) | ~300 |
| Phase 3 | 0 | 3 (pipeline_events, detect prompt, app.py) | ~150 |
| **Total** | **4 new files** | **14 modified files** | **~900 LOC** |
