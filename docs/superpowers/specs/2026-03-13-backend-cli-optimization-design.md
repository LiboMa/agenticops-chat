# Backend & CLI Optimization Design

**Date**: 2026-03-13
**Goal**: Reduce token costs, improve CLI startup, enhance long-conversation UX
**Scope**: Backend agents, CLI, config — no frontend changes

---

## 1. System Prompt Consolidation

### Problem

7 agents carry ~75 KB aggregate system prompts. Common instructions are duplicated:
- "Call get_active_account first" appears in main, scan, detect, rca, sre
- Skill activation guidance appears in main, rca, sre, executor (the 4 agents using `build_prompt_with_skills()`)
- Output format rules injected per-agent via `build_prompt_with_skills()`

Note: scan_agent and detect_agent do **not** use `build_prompt_with_skills()` and have no skill tools — they only share the account preamble instruction.

### Design

Extract a shared **agent preamble** module (`agents/preamble.py`) with composable blocks:

```python
# agents/preamble.py

ACCOUNT_PREAMBLE = """Call get_active_account and assume_role before any AWS operation.
If no account is configured, inform the user."""

SKILL_PREAMBLE = """..."""  # Current _SKILLS_USAGE_PROTOCOL from loader.py

OUTPUT_RULES = { "concise": "...", "medium": "...", "detailed": "..." }
# Moved from loader.py — single source of truth

def build_system_prompt(
    base: str,
    *,
    include_account: bool = True,
    include_skills: bool = True,
    agent_type: str = "generic",
) -> str:
    """Compose final system prompt from base + selected preamble blocks."""
```

**Per-agent changes:**
- `main_agent.py`: Remove redundant tool description blocks (METADATA TOOLS, NETWORK TOOLS, MONITORING — ~20 lines, ~1.2 KB). Keep routing rules + agent descriptions. **Target: ~7.9 KB → ~6.7 KB.**
- `scan_agent.py`, `detect_agent.py`: Extract single-line account instruction to preamble (minimal savings, consistency benefit).
- `rca_agent.py`, `sre_agent.py`, `executor_agent.py`: Remove duplicated skill activation guidance, use preamble. These are the main beneficiaries.

**Estimated savings**: 10-15% prompt tokens across agents using `build_prompt_with_skills()`.

### Files Changed

| File | Change |
|------|--------|
| `agents/preamble.py` | **New** — shared prompt blocks + `build_system_prompt()` |
| `agents/main_agent.py` | Remove redundant tool descriptions (~1.2 KB), use `build_system_prompt()` |
| `agents/scan_agent.py` | Extract account instruction to preamble (consistency) |
| `agents/detect_agent.py` | Extract account instruction to preamble (consistency) |
| `agents/rca_agent.py` | Remove duplicated skill/output rules, use preamble |
| `agents/sre_agent.py` | Remove duplicated skill/output rules, use preamble |
| `agents/executor_agent.py` | Remove skill duplication, use preamble |
| `agents/reporter_agent.py` | Use preamble for output rules |
| `skills/loader.py` | Move `_OUTPUT_RULES`, `_SKILLS_USAGE_PROTOCOL`, `get_output_rules()` → `preamble.py`. Keep `build_prompt_with_skills()` as thin wrapper calling `build_system_prompt()`. |

---

## 2. Skill Injection — On-Demand Instead of All-at-Once

### Problem

`build_prompt_with_skills()` appends an `<available_skills>` XML block listing **all** 10 skills. Each skill description is up to 1024 chars → ~3-5 KB added to every inference call for agents that use it (main, rca, sre, executor).

### Design

**Phase 1 (low effort)**: Trim the `<available_skills>` XML to name + one-line summary (max 80 chars per skill, not 1024). Total block drops from ~5 KB to ~1 KB.

```python
# loader.py — change build_available_skills_xml()
def build_available_skills_xml(skills: list[SkillMetadata]) -> str:
    lines = ["<available_skills>"]
    for s in skills:
        # Truncate to first sentence, max 80 chars
        short_desc = s.description.split(".")[0][:80]
        tag = "[DRAFT] " if s.is_draft else ""
        lines.append(f'  <skill name="{s.name}">{tag}{short_desc}</skill>')
    lines.append("</available_skills>")
    return "\n".join(lines)
```

**Phase 2 (optional, deferred)**: The `include_skills` flag in `build_system_prompt()` already controls this. Only main, rca, sre, executor pass `include_skills=True`.

**Note**: `reporter_agent.py` imports `activate_skill` and `read_skill_reference` as tools but does NOT call `build_prompt_with_skills()`, meaning it has skill tools without the `<available_skills>` XML. This is a latent inconsistency to address during implementation.

### Files Changed

| File | Change |
|------|--------|
| `skills/loader.py` | Truncate skill descriptions in XML to 80 chars |
| `agents/preamble.py` | `include_skills` flag controls XML injection |

**Estimated savings**: 3-4 KB per inference call for agents using skills.

---

## 3. Executor Model — Smart Tier Selection

### Problem

`executor_agent` uses Opus 4.6 ($15/$75 per 1M tokens) for ALL fix executions. L0 (restart service) and L1 (scale up) fixes are simple — Sonnet 4.6 ($3/$15) is sufficient.

### Design

Add two new config fields:

```python
# config.py
executor_smart_model: bool = Field(True, description="Use cheaper model for L0/L1 fixes")
executor_simple_model_id: str = Field(
    "global.anthropic.claude-sonnet-4-6",
    description="Model for L0/L1 executor (when executor_smart_model=True)"
)
```

The executor `@tool` function must **query the FixPlan from DB before creating the agent** to determine the risk level:

```python
# agents/executor_agent.py — inside the @tool function

from agenticops.models import get_db_session, FixPlan

def executor_agent(fix_plan_id: int) -> str:
    # 1. Query risk level BEFORE agent creation
    with get_db_session() as session:
        plan = session.query(FixPlan).get(fix_plan_id)
        if not plan:
            return f"Fix plan {fix_plan_id} not found"
        risk_level = plan.risk_level or "L3"

    # 2. Select model based on risk
    if settings.executor_smart_model and risk_level in ("L0", "L1"):
        model_id = settings.executor_simple_model_id  # Sonnet
    else:
        model_id = settings.agent_executor_model_id   # Opus

    # 3. Create agent with selected model
    model = BedrockModel(model_id=model_id, ...)
    agent = Agent(model=model, ...)
    ...
```

### Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `executor_smart_model: bool` and `executor_simple_model_id: str` |
| `config/settings.yaml` | Add `executor_smart_model: true` and `executor_simple_model_id` |
| `agents/executor_agent.py` | Query FixPlan risk level, select model accordingly |

**Estimated savings**: 40-60% cost reduction on executor calls (majority are L0/L1).

---

## 4. Per-Agent Sliding Window Size

### Problem

Global `bedrock_window_size: 40` applied to all agents.

**Key context**: Sub-agents (scan, detect, etc.) are created fresh per `@tool` invocation. Their window size only matters for internal multi-step tool loops. In practice:
- Scan/detect/reporter: Rarely exceed 5-10 internal turns → window size 40 vs 10 makes **no practical difference** in typical use.
- RCA/SRE: Can have 15-30 internal tool-call turns during complex investigations → **larger windows improve accuracy** by retaining earlier findings.
- Main agent: Persists for the session → window size directly affects long-conversation quality.

### Design

Add per-agent window size overrides. The primary value is **increasing RCA/SRE windows for accuracy**, not reducing scan/detect windows (which saves negligible tokens in practice).

```yaml
# config/settings.yaml
bedrock_window_size: 40          # global default (unchanged)
agent_rca_window_size: 60        # RCA needs deep history
agent_sre_window_size: 60        # SRE references RCA findings
agent_executor_window_size: 20   # executor follows a plan
# Other agents: 0 = use global default (no practical benefit to lowering)
```

Implementation in `config.py`:

```python
agent_rca_window_size: int = Field(0, description="RCA agent window (0=global)")
agent_sre_window_size: int = Field(0, description="SRE agent window (0=global)")
agent_executor_window_size: int = Field(0, description="Executor agent window (0=global)")
# ... etc for all 7

def get_agent_window_size(agent_name: str) -> int:
    override = getattr(settings, f"agent_{agent_name}_window_size", 0)
    return override if override > 0 else settings.bedrock_window_size
```

### Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `agent_X_window_size` fields + `get_agent_window_size()` |
| `config/settings.yaml` | Add window size overrides for RCA/SRE/executor |
| `agents/*.py` (all 7) | Use `get_agent_window_size(name)` in agent creation |

**Estimated impact**: RCA/SRE accuracy improvement for complex investigations. Minor token increase for those agents, offset by better first-pass success rate.

---

## 5. CLI Lazy Loading & Startup Optimization

### Problem

`cli/main.py` imports at top level (lines 1-66):
- Standard library: 13 modules
- `typer` + 12 Rich submodules
- `agenticops.config` (triggers YAML parsing)
- `agenticops.models` (triggers SQLAlchemy ORM setup)
- `agenticops.cli.formatters`, `display`, `context`

**Note**: Agent modules are NOT imported at top level — they're created inside the chat flow. The main import cost comes from SQLAlchemy (`agenticops.models`) and Rich.

### Design

**6a. Defer heavy imports** to function scope:

```python
# cli/main.py — top level: only typer + config + minimal imports
import typer
from typing import Optional

app = typer.Typer(...)

# Move to function scope:
# - agenticops.models (SQLAlchemy ORM init)
# - Rich submodules (12 imports)
# - agenticops.cli.formatters, display, context
```

This benefits non-chat commands (e.g., `aiops init`, `aiops --help`) that don't need SQLAlchemy or Rich display components.

**6b. Agent creation in background thread** for interactive mode:

```python
def chat_command(...):
    # Start agent creation in background while showing welcome message
    import threading
    agent_future = {}
    def _init():
        agent_future["agent"] = create_main_agent()
    t = threading.Thread(target=_init, daemon=True)
    t.start()

    # Show welcome banner + prompt (user types while agent initializes)
    show_welcome()
    user_input = prompt()

    # By now, agent is likely ready
    t.join()
    agent = agent_future["agent"]
```

**Benchmark requirement**: Measure `time aiops --help` and `time aiops chat --headless "health check"` before and after to validate actual improvement.

### Files Changed

| File | Change |
|------|--------|
| `cli/main.py` | Defer SQLAlchemy + Rich imports to function scope |
| `cli/main.py` | Background thread for agent init in interactive mode |

**Estimated improvement**: Faster `aiops --help` and non-chat commands. Perceived startup time reduction for chat (agent initializes while user types).

---

## 6. Cost Table in Config (Minor)

### Problem

Token cost rates are hardcoded in `cli/display.py` lines 96-100. Adding a new model requires a code change.

### Design

Move to `config/settings.yaml`:

```yaml
token_cost_table:
  claude-opus-4-6:
    input: 15.0
    output: 75.0
    cache_read: 1.50
  claude-sonnet-4-6:
    input: 3.0
    output: 15.0
    cache_read: 0.30
  claude-haiku-4-5:
    input: 0.80
    output: 4.0
    cache_read: 0.08
```

Add typed field to `config.py`:

```python
token_cost_table: dict[str, dict[str, float]] = Field(
    default={
        "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.50},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30},
        "claude-haiku-4-5": {"input": 0.80, "output": 4.0, "cache_read": 0.08},
    },
    description="Token cost rates per 1M tokens by model family"
)
```

### Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `token_cost_table: dict[str, dict[str, float]]` with default |
| `config/settings.yaml` | Add cost table |
| `cli/display.py` | Read from `settings.token_cost_table` instead of hardcoded dict |

---

## Summary: Implementation Order

| Step | Item | Effort | Impact |
|------|------|--------|--------|
| 1 | Prompt consolidation (preamble.py + trim main) | 1 day | ~10-15% prompt token reduction |
| 2 | Skill XML truncation | 0.5 day | ~3-4 KB reduction per inference |
| 3 | Executor smart model | 0.5 day | 40-60% cost reduction on executor (model tier, not tokens) |
| 4 | Per-agent window size | 0.5 day | RCA/SRE accuracy improvement |
| 5 | CLI lazy loading + bg init | 1 day | Startup UX improvement |
| 6 | Cost table in config | 0.5 day | Maintainability |
| **Total** | | **4 days** | |

**Overall cost impact**: Token reduction (~15-20%) + executor model tiering (~40-60% on executor subset) combine for an estimated **overall 20-35% cost reduction** depending on workload mix. UX improvements (CLI startup, RCA accuracy) are additive.

## Testing Strategy

- **Token regression test**: Run a fixed set of 5 queries (scan, detect, RCA, fix, report), measure input/output tokens before and after. Compare.
- **Accuracy test**: Same 5 queries, verify agent responses are equivalent quality.
- **CLI startup benchmark**: `time aiops --help` and `time aiops chat --headless "health check"` before/after.
- **Executor accuracy**: Run L0/L1 fix plans with Sonnet, compare to Opus baseline.

## Non-Goals

- No frontend changes
- No app.py/main.py split (deferred to 1.0.1)
- No cross-session agent sharing (complex state management, low ROI for current usage)
- No Strands SDK changes (work within existing API)
