# Proactive Agent Spec — ClawOps Phase 3

## Status: DRAFT
## Author: Architect (with Researcher research input)
## Date: 2026-03-10

---

## 1. Problem Statement

ClawOps currently operates **reactively** — alerts trigger RCA → fix → learn. For L5 autonomous
operations, the system must also operate **proactively**: predict issues before they become incidents
based on accumulated experience (Memory) and real-time signals.

### What "Proactive" Means in ClawOps

> "Not just anomaly detection — based on Memory pattern frequency. If an issue appears 3 times
> in the past 7 days, proactively alert." — Architect decision, Phase 3 planning

The key insight: **proactive behavior emerges from the agent's own learning, not from static
monitoring rules**. This is the L5 distinction.

## 2. Design Principles

1. **Memory-First**: Predictions based on accumulated RCA experience, not CloudWatch thresholds
2. **Read-Only (T0)**: Proactive Agent NEVER modifies infrastructure — only observes and warns
3. **Reuse Pipeline**: ProactiveAlert → existing `alert_pipeline` → `rca_agent` chain
4. **Confidence Ladder**: Start conservative (notify only), earn autonomy through accuracy

## 3. Architecture

### 3.1 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Proactive Agent                           │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ PatternWatch │  │ HealthProbe  │  │ PredictiveAlert  │  │
│  │              │  │              │  │                  │  │
│  │ Memory scan  │  │ Periodic     │  │ Generate alert   │  │
│  │ for recurring│  │ health       │  │ from prediction  │  │
│  │ patterns     │  │ checks       │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         └────────┬────────┘                    │            │
│                  ▼                             │            │
│         ┌────────────────┐                     │            │
│         │ RiskScorer     │─────────────────────┘            │
│         │ (threshold     │                                  │
│         │  based action) │                                  │
│         └────────────────┘                                  │
└─────────────────────────────────────────────────────────────┘
          │
          ▼ ProactiveAlert (StructuredAlert subtype)
┌─────────────────────────┐
│ alert_pipeline.py       │  ← existing, no changes
│ → alert_processor.py    │
│ → rca_agent             │
└─────────────────────────┘
```

### 3.2 New Files

```
src/agenticops/agents/proactive_agent.py    (~300 LOC)  — Main agent class
src/agenticops/proactive/                                — Proactive subsystem
├── __init__.py
├── pattern_watch.py      (~120 LOC)  — Memory-based pattern detection
├── health_probe.py       (~100 LOC)  — Periodic health checks
├── risk_scorer.py        (~80 LOC)   — Risk assessment + thresholds
└── predictive_alert.py   (~60 LOC)   — Generate ProactiveAlert
```

**Estimated total: ~660 LOC**

### 3.3 Reuse from agentic-aiops-mvp

| Component | agentic-aiops-mvp | ClawOps action |
|-----------|-------------------|----------------|
| `ProactiveAgentSystem` | 498 LOC, heartbeat loop | **Adapt** — keep loop, replace task system with Memory-driven |
| `_action_quick_scan` | CloudWatch metrics | **Adapt** — add Memory pattern check |
| `_auto_trigger_rca` | Direct RCA call | **Replace** — route through alert_pipeline |
| `TaskType` / `ProactiveTask` | Enum + dataclass | **Simplify** — ClawOps uses Strands agent model |

## 4. Core Components

### 4.1 PatternWatch — Memory-based Prediction

The heart of the Proactive Agent. Queries AgentMemory for recurring patterns.

```python
class PatternWatch:
    """Detect recurring incident patterns from agent memory."""

    RECURRENCE_THRESHOLD = 3       # N occurrences in window → alert
    RECURRENCE_WINDOW_DAYS = 7     # Look-back window
    CONFIDENCE_DECAY = 0.95        # Per-day confidence decay

    async def scan(self, memory: AgentMemory) -> list[PatternAlert]:
        """Scan memory for recurring patterns.

        Algorithm:
        1. Recall recent episodic + semantic memories (past 7 days)
        2. Group by root_cause_category (from RCALearner)
        3. If count >= RECURRENCE_THRESHOLD → generate PatternAlert
        4. Score by frequency * recency * avg_confidence
        """
        recent = await memory.recall(
            "recurring incidents patterns failures",
            top_k=50,
            min_confidence=0.3,
        )
        # Group by category
        categories: dict[str, list[MemoryEntry]] = {}
        for entry in recent:
            cat = self._extract_category(entry)
            categories.setdefault(cat, []).append(entry)

        alerts = []
        for cat, entries in categories.items():
            if len(entries) >= self.RECURRENCE_THRESHOLD:
                score = self._score_pattern(entries)
                alerts.append(PatternAlert(
                    category=cat,
                    occurrences=len(entries),
                    score=score,
                    recent_entries=entries[:5],
                ))
        return sorted(alerts, key=lambda a: a.score, reverse=True)
```

### 4.2 HealthProbe — Periodic Checks

Lightweight health checks that run on a heartbeat interval.

```python
class HealthProbe:
    """Periodic health checks with memory-informed focus areas."""

    DEFAULT_INTERVAL = 300  # 5 minutes

    async def probe(self, memory: AgentMemory) -> list[HealthIssue]:
        """Run health checks, prioritizing areas with recent incidents.

        Strategy:
        1. Check memory for recent RCA categories
        2. Prioritize checks for those categories
        3. Run standard checks for remaining areas
        """
        # Memory-informed: focus on areas with recent issues
        focus_areas = await self._get_focus_areas(memory)

        issues = []
        for area in focus_areas:
            result = await self._check_area(area)
            if result.is_degraded:
                issues.append(result)
        return issues
```

### 4.3 RiskScorer — Decision Engine

```python
class RiskScorer:
    """Score risk and decide action level."""

    # Confidence Ladder (Architect + Researcher consensus)
    NOTIFY_THRESHOLD = 0.3      # Just log + notify channel
    WARN_THRESHOLD = 0.65       # Create ProactiveAlert → trigger RCA evaluation (Researcher: 0.6→0.65 reduce noise)
    ESCALATE_THRESHOLD = 0.85   # Escalate to SRE agent (still read-only)

    def score(self, pattern: PatternAlert, health: list[HealthIssue]) -> RiskLevel:
        """Combine pattern frequency + current health into risk score."""
        base = pattern.score
        # Boost if current health shows degradation in same area
        health_boost = 0.2 if any(h.area == pattern.category for h in health) else 0.0
        final = min(1.0, base + health_boost)

        if final >= self.ESCALATE_THRESHOLD:
            return RiskLevel.ESCALATE
        elif final >= self.WARN_THRESHOLD:
            return RiskLevel.WARN
        elif final >= self.NOTIFY_THRESHOLD:
            return RiskLevel.NOTIFY
        return RiskLevel.IGNORE
```

### 4.4 PredictiveAlert — Alert Generation

```python
class PredictiveAlert:
    """Generate ProactiveAlert compatible with existing alert pipeline."""

    @staticmethod
    def create(pattern: PatternAlert, risk: RiskLevel) -> StructuredAlert:
        """Create a StructuredAlert for the existing pipeline."""
        return StructuredAlert(
            source="proactive_agent",
            alert_type=f"predictive:{pattern.category}",
            severity=risk.to_severity(),  # WARN→medium, ESCALATE→high
            title=f"Predicted: {pattern.category} ({pattern.occurrences}x in 7d)",
            description=(
                f"Pattern detected: {pattern.category} has occurred "
                f"{pattern.occurrences} times in the past 7 days. "
                f"Risk score: {pattern.score:.2f}"
            ),
            resource_id=pattern.category,
            timestamp=datetime.utcnow(),
            metadata={
                "prediction_type": "pattern_recurrence",
                "occurrences": pattern.occurrences,
                "risk_score": pattern.score,
            },
        )
```

## 5. Agent Integration

### 5.1 ProactiveAgent class

```python
class ProactiveAgent:
    """Memory-driven proactive operations agent.

    Security: T0 (read-only). Never modifies infrastructure.
    Heartbeat: Runs PatternWatch + HealthProbe on configurable interval.
    Output: ProactiveAlert → alert_pipeline → rca_agent chain.
    """

    def __init__(
        self,
        memory: AgentMemory,
        alert_pipeline: AlertPipeline,
        interval_seconds: int = 300,
    ):
        self.memory = memory
        self.alert_pipeline = alert_pipeline
        self.interval = interval_seconds
        self.pattern_watch = PatternWatch()
        self.health_probe = HealthProbe()
        self.risk_scorer = RiskScorer()
        self._running = False

    async def start(self):
        """Start the proactive loop."""
        self._running = True
        bind_agent("proactive_agent")  # T0 lock
        while self._running:
            await self._cycle()
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        """Single proactive cycle: scan → score → alert."""
        patterns = await self.pattern_watch.scan(self.memory)
        health = await self.health_probe.probe(self.memory)

        for pattern in patterns:
            risk = self.risk_scorer.score(pattern, health)
            if risk >= RiskLevel.WARN:
                alert = PredictiveAlert.create(pattern, risk)
                await self.alert_pipeline.ingest(alert)
                await self.memory.remember(
                    content=f"PROACTIVE_ALERT: {pattern.category}, risk={risk.name}",
                    memory_type=MemoryType.EPISODIC,
                    source="proactive_agent",
                    confidence=pattern.score,
                )
```

### 5.2 Registration

Add to `agents/__init__.py` and agent binding:
```python
# Already in agent_binding.py:
"proactive_agent": SecurityTier.T0_READONLY,
```

## 6. Safety Constraints

| Constraint | Implementation |
|-----------|---------------|
| Read-only | `@secure_tool(tier=T0)` on all tools; `bind_agent("proactive_agent")` = T0 |
| No auto-fix | ProactiveAgent generates alerts only; fix decisions are RCA → SRE chain |
| Rate limit | Max 5 ProactiveAlerts per hour (prevent alert storm) |
| Confidence gate | Only WARN+ (≥0.6) generates alerts to pipeline |
| Memory-first | Pattern detection MUST use agent memory, not hardcoded rules |

## 7. Relationship to Existing Components

```
proactive_agent (NEW, T0)
    │
    │ ProactiveAlert (StructuredAlert subtype)
    ▼
alert_pipeline.py (EXISTING, no changes)
    │
    ▼
alert_processor.py (EXISTING, no changes)
    │
    ▼
rca_agent (EXISTING, T1)
    │
    ▼
DeepRCAEngine (EXISTING)
    │
    ▼
RCALearner (EXISTING)
    │
    ▼
Memory (feedback loop → proactive_agent learns from outcomes)
```

## 8. Implementation Plan

| Step | What | LOC | Time |
|------|------|-----|------|
| 1 | `proactive/pattern_watch.py` + tests | ~150 | 30 min |
| 2 | `proactive/health_probe.py` + tests | ~130 | 30 min |
| 3 | `proactive/risk_scorer.py` + tests | ~100 | 20 min |
| 4 | `proactive/predictive_alert.py` + tests | ~80 | 15 min |
| 5 | `agents/proactive_agent.py` + integration | ~200 | 45 min |
| 6 | E2E: pattern recurrence → alert → RCA chain | ~100 | 30 min |
| **Total** | | **~760** | **~3 hrs** |

## 9. Success Criteria

1. PatternWatch detects recurring incidents from memory (≥3 in 7 days)
2. ProactiveAlert flows through existing alert_pipeline without changes
3. Proactive Agent locked to T0 — verified by @secure_tool tests
4. Zero false positives in initial deployment (threshold ≥0.6)
5. Feedback loop: RCA outcomes inform next proactive cycle
6. Rate limiting: max 5 alerts/hour

## 10. References

- Researcher: MetaGPT multi-agent coordination, LLM Multi-Agent Systems (2024)
- Architect: Memory-driven prediction > rule-based monitoring (L5 insight)
- agentic-aiops-mvp: `src/proactive_agent.py` (498 LOC, heartbeat loop pattern)
- Phase 2: AgentMemory, RCALearner, SkillGapDetector (all feed into proactive)
- ADR-010: L3→L5 roadmap, Phase 3 = L4.5 (Predictive Memory)
