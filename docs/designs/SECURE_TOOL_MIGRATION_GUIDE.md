# @secure_tool Migration Guide — ClawOps Phase 3

## Status: DRAFT
## Author: Architect
## Date: 2026-03-10

---

## 1. Overview

Migrate the 4-tier `@secure_tool` security framework from `agentic-aiops-mvp` into ClawOps,
layering it on top of ClawOps' existing `skills/security.py` command classification.

**Goal**: Every `@tool` in ClawOps gets a SecurityTier (T0-T3). Agent-level binding
controls which tier each agent can invoke. T2+ requires HMAC approval tokens.

## 2. Source Files (agentic-aiops-mvp)

| File | LOC | Purpose |
|------|-----|---------|
| `src/skills/_models.py` | 89 | `SecurityTier(IntEnum)`, `ToolResult`, `SkillManifest` |
| `src/skills/_security.py` | 263 | `@secure_tool` decorator — 5-layer defense |
| `src/approval_token.py` | 107 | HMAC token gen/verify with TTL |
| `src/skills/agent_binding.py` | 160 | `AGENT_TIER_BINDINGS`, `bind_skills_to_agent()` |
| **Total** | **619** | |

## 3. Target Integration in ClawOps

### 3.1 What to KEEP in ClawOps (don't replace)

- `skills/security.py` → `classify_shell_command()` + `classify_kubectl_command()`
  - These become **Layer 3** (command-level classification) inside `@secure_tool`
  - Map: `readonly` → T0, `write` → T1, `blocked` → T3

### 3.2 What to ADD

```
src/agenticops/skills/
├── security.py          ← KEEP (existing, 194 LOC)
├── secure_tool.py       ← NEW: @secure_tool decorator (~220 LOC)
├── security_models.py   ← NEW: SecurityTier, ToolResult (~60 LOC)
├── approval_token.py    ← NEW: HMAC token gen/verify (~100 LOC)
└── agent_binding.py     ← NEW: AGENT_TIER_BINDINGS for 7 agents (~120 LOC)
```

### 3.3 SecurityTier Definition

```python
class SecurityTier(IntEnum):
    T0 = 0  # Read-only diagnostic (auto-execute)
    T1 = 1  # State-modifying (logged, auto-execute)
    T2 = 2  # Risky operations (requires HMAC approval token)
    T3 = 3  # Destructive/irreversible (requires dual approval)
```

### 3.4 Agent Tier Bindings (ClawOps 7 agents)

```python
AGENT_TIER_BINDINGS = {
    "scan_agent":      SecurityTier.T0,   # Read-only scanning
    "detect_agent":    SecurityTier.T0,   # Read-only detection
    "rca_agent":       SecurityTier.T1,   # Diagnostic + evidence collection
    "reporter_agent":  SecurityTier.T0,   # Read-only reporting
    "executor_agent":  SecurityTier.T2,   # Remediation (needs approval)
    "sre_agent":       SecurityTier.T3,   # Full ops (needs dual approval)
    "main_agent":      SecurityTier.T1,   # Coordinator
    "proactive_agent": SecurityTier.T0,   # Phase 3: READ-ONLY (Architect decision)
}
```

### 3.5 @secure_tool 5-Layer Defense

```
Layer 1: Tier check — agent's max tier >= tool's required tier
Layer 2: Rate limiting — per-agent, per-tool call frequency
Layer 3: Command classification — reuse existing classify_shell_command()
Layer 4: Approval token — T2+ requires valid HMAC token
Layer 5: Audit logging — all executions logged with agent, tier, timestamp
```

## 4. Mapping: ClawOps risk_level → SecurityTier

| ClawOps `classify_*()` result | SecurityTier |
|-------------------------------|-------------|
| `readonly` | T0 |
| `write` | T1 |
| `blocked` | T3 |
| (new) `risky` | T2 |

## 5. Implementation Steps

### Step 1: Add security_models.py (~30 min)
- Port `SecurityTier`, `ToolResult` from `_models.py`
- Adapt to ClawOps naming conventions

### Step 2: Add secure_tool.py (~1 hr)
- Port `@secure_tool` decorator
- Wire Layer 3 to existing `classify_shell_command()` / `classify_kubectl_command()`
- Add `contextvars` for agent context (reuse WAL's pattern)

### Step 3: Add approval_token.py (~30 min)
- Port HMAC token generation and verification
- Use `CLAWOPS_APPROVAL_SECRET` env var (not hardcoded)

### Step 4: Add agent_binding.py (~30 min)
- Define `AGENT_TIER_BINDINGS` for all 7+1 agents
- Implement `bind_skills_to_agent()` that filters tools by tier

### Step 5: Annotate existing tools (~1 hr)
- Add `@secure_tool(tier=T0)` to all read-only tools
- Add `@secure_tool(tier=T1)` to state-modifying tools
- Add `@secure_tool(tier=T2)` to remediation tools
- Add `@secure_tool(tier=T3)` to destructive tools

### Step 6: Tests (~1 hr)
- Port existing 113 skills tests from agentic-aiops-mvp
- Add ClawOps-specific integration tests
- Verify agent binding with actual tool lists

## 6. Estimated Effort

- **~500 LOC new code** (port + adapt)
- **~4 hours** (Developer with Claude Code)
- **0 breaking changes** — existing tools continue to work, `@secure_tool` is additive

## 7. Success Criteria

1. All 7 agents respect tier bindings
2. T2+ tools reject without valid HMAC token
3. `classify_shell_command()` integrated as Layer 3
4. Audit log captures all tool executions
5. Zero regression in existing tests
6. Proactive Agent locked to T0 (read-only)

## 8. References

- agentic-aiops-mvp `src/skills/_security.py` (263 LOC)
- ADR-009 SkillBridge design
- Phase 2 WAL `contextvars` pattern (commit `4aa022a`)
