# Deep RCA Engine Spec

> **Author**: Architect  
> **Date**: 2026-03-10  
> **Status**: DRAFT — awaiting Researcher + Reviewer feedback  
> **ADR**: Part of ADR-010 Phase 1  
> **Priority**: P0 — next delivery after Memory System

---

## 1. Problem Statement

Current RCA (`analyze/rca.py` RCAEngine + `agents/rca_agent.py`) is **single-pass**:

```
Issue → LLM prompt → one response → save → done
```

Problems:
1. **No iteration on low confidence** — if confidence < 0.7, result is saved as-is
2. **No evidence gathering loop** — RCA Agent has tools but no mechanism to re-investigate
3. **No memory integration** — doesn't recall past similar incidents
4. **No cross-agent evidence sharing** — SRE findings don't feed back to RCA
5. **Two RCA paths coexist** — `RCAEngine` (direct LLM) and `rca_agent` (Strands Agent) are disconnected

## 2. Goals

| Goal | Metric |
|------|--------|
| Iterative RCA with confidence threshold | RCA loops until confidence ≥ 0.7 or max 3 iterations |
| Memory-augmented investigation | Every RCA starts with `recall_memories()` |
| Evidence accumulation across iterations | Each loop adds new evidence, narrowing scope |
| Unified RCA path | Single `DeepRCAEngine` replaces both `RCAEngine` and raw agent call |
| Backward compatible | Existing `rca_agent` @tool signature unchanged |

## 3. Architecture

### 3.0 Dual-Path Design (Researcher recommendation, based on RCACopilot + Voyager)

> **Key insight**: Not every RCA needs full LLM reasoning. Memory-first fast path 
> should handle recurring patterns in <1s. Deep path only for novel incidents.

```
Alert → RCARouter
          ├── Fast Path (Memory recall, <1s)
          │     → High-confidence memory match (≥0.9)? → Return immediately
          │
          └── Deep Path (Iterative LLM, 10-30s)
                → Evidence gathering + iteration loop
                → Self-verification (Voyager CriticAgent pattern)
                → Post-RCA learning (LearnAct revision-first)
```

**Target metrics** (ref: Microsoft RCACopilot achieves 76.6% accuracy):

| Metric | Target | Source |
|--------|--------|--------|
| RCA accuracy | >80% | Exceed RCACopilot 76.6% |
| Fast Path hit rate | >40% (grows with memory) | Novel |
| Fast Path latency | <1s | Memory recall only |
| Deep Path latency | <30s | Max 3 iterations |
| Learning rate | 1 new/improved Skill per 10 incidents | LearnAct pattern |

### 3.1 Iteration Loop (Deep Path)

```
┌─────────────────────────────────────────────────────┐
│                  DeepRCAEngine                       │
│                                                      │
│  1. recall_memories(issue symptoms)                  │
│  2. search_similar_cases(symptoms)                   │
│  3. search_sops(resource_type)                       │
│       ↓                                              │
│  ┌─── Iteration Loop (max_iterations=3) ────┐       │
│  │                                           │       │
│  │  4. Build prompt (issue + evidence + KB)  │       │
│  │  5. LLM analysis → RCAResult             │       │
│  │  6. Extract confidence                    │       │
│  │                                           │       │
│  │  if confidence ≥ 0.7:                     │       │
│  │     → BREAK (sufficient confidence)       │       │
│  │                                           │       │
│  │  7. Identify evidence gaps                │       │
│  │  8. Gather additional evidence:           │       │
│  │     - CloudTrail (deeper time range)      │       │
│  │     - CloudWatch (additional metrics)     │       │
│  │     - Network topology (if relevant)      │       │
│  │     - Traces (if service degradation)     │       │
│  │  9. Append to evidence_chain              │       │
│  │                                           │       │
│  └───────────────────────────────────────────┘       │
│       ↓                                              │
│  10. remember_this(final RCA result)                 │
│  11. save_rca_result()                               │
│  12. Return DeepRCAResult                            │
└─────────────────────────────────────────────────────┘
```

### 3.2 Data Model

```python
@dataclass
class EvidenceItem:
    """Single piece of investigation evidence."""
    source: str          # "cloudtrail" | "cloudwatch" | "kb" | "memory" | "trace" | "network"
    content: str         # Human-readable evidence text
    confidence_delta: float  # How much this evidence shifts confidence (-1.0 to 1.0)
    timestamp: datetime
    raw_data: dict = field(default_factory=dict)


@dataclass
class DeepRCAResult:
    """Result from iterative deep RCA."""
    issue_id: int
    root_cause: str
    confidence: float                          # Final confidence after all iterations
    iterations: int                            # How many loops it took
    evidence_chain: list[EvidenceItem]         # Accumulated evidence across iterations
    contributing_factors: list[str]
    recommendations: list[str]
    fix_plan: dict                             # Step-by-step remediation
    fix_risk: str                              # low | medium | high | critical
    memory_matches: list[dict]                 # Past similar incidents from memory
    kb_matches: list[dict]                     # SOPs + similar cases from KB
    iteration_history: list[dict]              # Per-iteration: {confidence, evidence_count, gaps}
    duration_ms: int
```

### 3.3 Evidence Gap Detection

After each iteration with confidence < 0.7, the engine asks the LLM:

```
Given the current evidence and confidence of {confidence}, 
what additional information would most help determine the root cause?

Return a JSON list of evidence requests:
[
  {"type": "cloudtrail", "params": {"lookback_hours": 48}},
  {"type": "cloudwatch", "params": {"metrics": ["CPUUtilization", "NetworkIn"]}},
  {"type": "network", "params": {"check": "security_groups"}},
  {"type": "trace", "params": {"service": "checkout-service"}}
]
```

The engine executes these requests and adds results to `evidence_chain`.

### 3.4 Self-Verification (Researcher: Voyager CriticAgent pattern)

After the iteration loop produces a result, a verification step challenges the conclusion:

```python
VERIFY_PROMPT = """
You are a critical reviewer of RCA conclusions.
Given:
- Root cause: {root_cause}
- Evidence chain: {evidence_summary}
- Confidence: {confidence}

Questions:
1. Does the evidence actually support this root cause, or is it merely correlated?
2. Are there alternative explanations the analysis missed?
3. Is the confidence score justified given the evidence quality?

Return: {"valid": true/false, "critique": "...", "adjusted_confidence": 0.X}
"""
```

If `valid=false`, the engine runs one more iteration with the critique as additional context.

### 3.5 Post-RCA Learning (Researcher: LearnAct revision-first)

```python
class RCALearner:
    """Async post-RCA learning — fire and forget after returning result."""
    
    async def learn(self, result: DeepRCAResult):
        # 1. Remember (WAL)
        await self._remember_outcome(result)
        
        # 2. Revision-first skill update (LearnAct pattern)
        #    Try to improve existing Skill BEFORE creating new one
        existing = await skill_registry.find_similar(result.root_cause_category)
        if existing:
            await skill_registry.revise(existing, learnings=result)
        elif self._should_create_skill(result):
            await skill_registry.create_draft(result)
        
        # 3. Periodic reflection (Generative Agents)
        if await self._incident_count_today() >= 5:
            memory = get_agent_memory("rca_agent")
            await memory.reflect()
```

## 4. Memory Integration

### 4.1 Pre-investigation Recall

```python
async def _pre_investigate(self, issue: HealthIssue) -> list[MemoryEntry]:
    """Recall relevant past experiences before starting RCA."""
    memory = get_agent_memory("rca_agent")
    
    # Search by symptoms
    symptom_query = f"{issue.resource_type} {issue.title} {issue.severity}"
    memories = await memory.recall(symptom_query, top_k=5)
    
    # Inject into prompt as "Past Experience" section
    return memories
```

### 4.2 Post-investigation Remember

```python
async def _post_investigate(self, result: DeepRCAResult):
    """Store investigation outcome for future recall."""
    memory = get_agent_memory("rca_agent")
    
    # Store as EPISODIC memory
    await memory.remember(
        content=f"RCA for {result.root_cause}: confidence={result.confidence}, "
                f"iterations={result.iterations}, fix={result.recommendations[0]}",
        memory_type=MemoryType.EPISODIC,
        source=f"rca:issue-{result.issue_id}",
    )
    
    # If high confidence, also store as PROCEDURAL (reusable pattern)
    if result.confidence >= 0.8:
        await memory.remember(
            content=f"PATTERN: {result.contributing_factors} → {result.root_cause}. "
                    f"Fix: {result.fix_plan.get('steps', ['unknown'])[0]}",
            memory_type=MemoryType.PROCEDURAL,
            source=f"rca:pattern:issue-{result.issue_id}",
        )
```

## 5. Unification: RCAEngine + rca_agent → DeepRCAEngine

### Current State (two disconnected paths):

```
Path A: RCAEngine.analyze_anomaly() → direct LLM call → RCAAnalysis
Path B: rca_agent(issue_id) → Strands Agent → free-form investigation
```

### Target State (unified):

```
rca_agent(issue_id) → DeepRCAEngine.investigate(issue_id) → DeepRCAResult
                         ↓
                     Uses Strands Agent internally for tool execution
                     Uses iteration loop for confidence threshold
                     Uses memory for past experience
```

### Migration:
1. `DeepRCAEngine` wraps a Strands Agent (same tools as current `rca_agent`)
2. `RCAEngine` becomes a lightweight fallback for cases without Strands SDK
3. `rca_agent` @tool calls `DeepRCAEngine.investigate()` instead of creating ad-hoc Agent

## 6. Implementation Plan

### Files to create/modify:

| File | Action | Est. LOC |
|------|--------|----------|
| `src/agenticops/analyze/deep_rca.py` | **NEW** — DeepRCAEngine + RCARouter + Fast/Deep paths | ~400 |
| `src/agenticops/analyze/evidence.py` | **NEW** — Evidence gathering functions (per source type) | ~200 |
| `src/agenticops/analyze/rca_learner.py` | **NEW** — Post-RCA learning + self-verification | ~150 |
| `src/agenticops/agents/rca_agent.py` | **MODIFY** — Call RCARouter instead of ad-hoc Agent | ~30 |
| `src/agenticops/tools/memory_tools.py` | **MODIFY** — Wire set_current_agent in rca_agent | ~5 |
| `tests/test_deep_rca.py` | **NEW** — Unit + integration tests | ~250 |
| **Total** | | **~1,085** |

### Implementation Order (for Developer):

```
1. analyze/evidence.py      — Evidence model + gatherers (standalone, testable)
2. analyze/deep_rca.py      — RCARouter + FastRCA + DeepRCA with iteration loop
3. analyze/rca_learner.py   — Self-verification + post-RCA learning + revision-first
4. agents/rca_agent.py      — Wire RCARouter into existing @tool
5. tests/test_deep_rca.py   — Full test coverage
```

## 7. Configuration

```python
# In config or as DeepRCAEngine.__init__ params
DEEP_RCA_CONFIG = {
    "max_iterations": 3,              # Max investigation loops
    "confidence_threshold": 0.7,      # Stop when confidence >= this
    "evidence_lookback_hours": 24,    # Initial CloudTrail window
    "evidence_lookback_expand": 2.0,  # Multiply lookback each iteration
    "memory_top_k": 5,               # Past incidents to recall
    "kb_top_k": 3,                   # SOPs + cases to retrieve
    "timeout_seconds": 120,           # Max wall-clock per investigation
}
```

## 8. Test Strategy

| Test Category | Count | Description |
|---------------|-------|-------------|
| Unit: EvidenceItem/DeepRCAResult | 5 | Data model creation, serialization |
| Unit: Evidence gap detection | 5 | LLM returns gap requests, engine parses |
| Unit: Iteration logic | 8 | Confidence threshold, max iterations, timeout |
| Unit: Memory integration | 5 | Pre-recall, post-remember, pattern extraction |
| Integration: Full investigation | 5 | Mock tools, verify iteration + evidence chain |
| Edge: No KB matches | 2 | Graceful degradation |
| Edge: All iterations low confidence | 2 | Returns best-effort with explanation |
| **Total** | **~32** | |

## 9. Success Criteria

1. ✅ RCA iterates when confidence < 0.7 (up to 3 times)
2. ✅ Evidence chain grows with each iteration
3. ✅ Memory recall before investigation, remember after
4. ✅ High-confidence patterns stored as PROCEDURAL memory
5. ✅ `rca_agent` @tool unchanged (backward compatible)
6. ✅ All existing RCA tests still pass
7. ✅ ~32 new tests, ≥90% coverage on new code

## 10. Open Questions (for Researcher) — PARTIALLY RESOLVED

1. **Confidence calibration** — ~~Should we use LLM self-reported confidence or compute it from evidence count/quality?~~ 
   **RESOLVED**: Use hybrid — LLM self-report + Self-Verification step (§3.4) to challenge and adjust. RCACopilot uses alert-type-specific handlers which implicitly calibrate per category.

2. **Evidence weighting** — ~~CloudTrail evidence should carry more weight than metric anomaly?~~
   **RESOLVED** (Architect + Researcher consensus):
   ```
   1. CloudTrail change events    0.95  (明确因果: "找到谁改了什么 = 80% root cause")
   2. Traces (error spans)        0.90  (直接定位)
   3. Metrics (anomaly)           0.85  (强相关)
   4. Logs (error patterns)       0.80  (丰富但噪音)
   5. Memory (historical)         0.70  (经验参考)
   6. Graph/Topology              0.60  (推理依赖图完整度)
   7. LLM reasoning               0.50  (综合判断)
   8. External KB/SOP             0.40  (通用参考)
   ```
   Phase 2 实现: evidence.py gatherer 返回 `weight` 属性, deep_rca.py 加权求和

3. **Cross-agent teaching** — ~~When RCA discovers a new pattern, should it proactively notify Detect Agent?~~
   **RESOLVED**: Yes, via publish-subscribe (Architect + Researcher consensus). RCALearner (§3.5) handles this via `skill_registry.revise()` / `create_draft()`.

4. **NEW: Revision-first vs create-first** (Researcher, from LearnAct) — When should the system revise an existing Skill vs create a new one? 
   **Proposal**: If `find_similar()` returns match with similarity > 0.7, revise. Otherwise create draft.

---

*Spec version: 1.2 (all open questions resolved, evidence hierarchy finalized) | Architect | 2026-03-10*

---

## Addendum: Phase 2 Implementation Items

### A1. Evidence Weighting
```python
# evidence.py — each gatherer returns weight
EVIDENCE_WEIGHTS = {
    "cloudtrail": 0.95,
    "trace": 0.90,
    "cloudwatch": 0.85,
    "logs": 0.80,
    "memory": 0.70,
    "network": 0.60,
    "llm": 0.50,
    "kb": 0.40,
}
```

### A2. Self-Verify Re-iteration
```python
# deep_rca.py — after Step 5
if not result.verified and result.iterations < self.MAX_ITERATIONS:
    # Inject critique into context
    context["self_verify_critique"] = critique_text
    # Re-enter iteration loop for one more pass
    result.iterations += 1
    # ... (same iteration logic with critique-enriched prompt)
```
