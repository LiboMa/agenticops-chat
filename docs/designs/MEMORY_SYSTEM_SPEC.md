# Per-Agent Memory System — Detailed Design Spec

> **Status**: DRAFT — Phase 1 deliverable
> **Author**: Architect
> **Date**: 2026-03-10
> **Parent**: ADR-010 §4.1 (ClawOps Architecture Evolution)
> **For**: Developer (Claude Code implementation)

---

## 1. Overview

Every ClawOps Agent gets persistent, searchable memory that survives across sessions.
The design reuses existing `kb/vector_store.py` (SQLiteVectorStore) and `kb/embeddings.py`
(BedrockTitanEmbedding) — no new infrastructure dependencies.

### Design Principles

1. **Reuse, don't reinvent** — build on existing `kb/` modules
2. **Isolation** — each agent's memory is separate (no cross-contamination)
3. **Shared knowledge via KB** — agents share through CaseStudy, not by reading each other's memory
4. **Lightweight** — MEMORY.md for human readability + vector DB for semantic search
5. **Bounded** — automatic consolidation prevents unbounded growth

---

## 2. Module Structure

```
src/agenticops/memory/
├── __init__.py           # AgentMemory factory
├── agent_memory.py       # Core AgentMemory class
├── consolidator.py       # End-of-day memory consolidation
└── types.py              # MemoryEntry, MemoryType enums
```

---

## 3. Data Model

### 3.1 MemoryEntry

```python
# src/agenticops/memory/types.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MemoryType(str, Enum):
    """Types of memory entries."""
    EPISODIC = "episodic"       # "Last time EKS pod crashed, it was OOM"
    PROCEDURAL = "procedural"   # "To restart ECS service, use aws ecs update-service"
    SEMANTIC = "semantic"       # "EKS node groups auto-scale based on pending pods"
    REFLECTION = "reflection"   # End-of-day summary


@dataclass
class MemoryEntry:
    """Single memory entry for an agent."""
    agent_name: str
    memory_type: MemoryType
    content: str                          # Natural language description
    context: dict = field(default_factory=dict)  # Structured metadata
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""                      # What triggered this memory (e.g., "rca:issue-42")
    confidence: float = 1.0               # 0.0-1.0, decays over time
    recall_count: int = 0                 # How often this memory was retrieved

    @property
    def memory_id(self) -> str:
        """Unique ID: agent_name:timestamp_iso."""
        return f"{self.agent_name}:{self.timestamp.isoformat()}"
```

### 3.2 Storage Schema

**SQLite table** (in the existing `agenticops.db`):

```sql
CREATE TABLE IF NOT EXISTS agent_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    memory_type TEXT NOT NULL,          -- episodic/procedural/semantic/reflection
    content TEXT NOT NULL,
    context_json TEXT DEFAULT '{}',
    source TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    recall_count INTEGER DEFAULT 0,
    vector BLOB,                        -- embedding (nullable: NullEmbeddingClient fallback)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_am_agent ON agent_memories(agent_name);
CREATE INDEX IF NOT EXISTS idx_am_type ON agent_memories(agent_name, memory_type);
CREATE INDEX IF NOT EXISTS idx_am_created ON agent_memories(created_at DESC);
```

### 3.3 MEMORY.md Format (Human-Readable)

Each agent also maintains a markdown file at `data/memory/{agent_name}_MEMORY.md`:

```markdown
# RCA Agent Memory

## 2026-03-10

### Episodic
- [07:23] EKS pod crash on cluster prod-us-east-1: OOM kill (container limit 512Mi, actual 847Mi)
  - Fix: Increased memory limit to 1Gi, added HPA with memory target 80%
  - Source: rca:issue-42
  - Confidence: 0.95

### Procedural
- Redis connection timeout diagnosis: Check `client list` → `info clients` → `slowlog get 10`
  - Learned from: rca:issue-38

### Reflection
- Today I analyzed 3 incidents. Pattern: 2/3 were resource limits (OOM). Suggest proactive memory monitoring.
```

---

## 4. Core API

### 4.1 AgentMemory Class

```python
# src/agenticops/memory/agent_memory.py

from pathlib import Path
from typing import Optional

from agenticops.kb.embeddings import get_embedding_client
from agenticops.memory.types import MemoryEntry, MemoryType


class AgentMemory:
    """Per-agent persistent memory with episodic + semantic storage."""

    MAX_MEMORIES_PER_AGENT = 1000   # Hard limit, oldest pruned
    CONSOLIDATION_THRESHOLD = 50     # Trigger consolidation after N new entries/day

    def __init__(self, agent_name: str, db_path: str | Path):
        self.agent_name = agent_name
        self._db_path = str(db_path)
        self._memory_md_path = Path(f"data/memory/{agent_name}_MEMORY.md")
        self._embedding_client = get_embedding_client()
        self._ensure_table()

    # ── Write ──────────────────────────────────────────────────

    async def remember(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        context: dict | None = None,
        source: str = "",
        confidence: float = 1.0,
    ) -> MemoryEntry:
        """Store a new memory entry.

        1. Create MemoryEntry
        2. Embed content → vector
        3. Insert into SQLite
        4. Append to MEMORY.md
        5. Check if consolidation needed

        Returns:
            The created MemoryEntry
        """
        ...

    # ── Read ───────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        memory_type: MemoryType | None = None,
        top_k: int = 5,
        min_confidence: float = 0.3,
    ) -> list[MemoryEntry]:
        """Semantic search across agent's memories.

        1. Embed query
        2. Cosine similarity search in SQLite
        3. Filter by confidence threshold
        4. Increment recall_count on returned entries
        5. Return top_k results

        Args:
            query: Natural language search query
            memory_type: Filter by type (None = all types)
            top_k: Maximum results
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching MemoryEntry, sorted by relevance
        """
        ...

    async def recall_recent(
        self,
        limit: int = 10,
        memory_type: MemoryType | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve most recent memories (chronological, not semantic)."""
        ...

    # ── Reflect ────────────────────────────────────────────────

    async def reflect(self) -> str:
        """End-of-day consolidation and summary.

        1. Gather today's memories
        2. Use LLM to generate summary (patterns, lessons)
        3. Store as REFLECTION type
        4. Prune low-confidence + low-recall entries
        5. Update MEMORY.md with reflection section

        Returns:
            The reflection summary text
        """
        ...

    # ── Maintenance ────────────────────────────────────────────

    async def prune(self, keep: int | None = None) -> int:
        """Remove oldest/lowest-confidence memories beyond limit.

        Strategy:
        1. Never prune REFLECTION entries (they're compressed summaries)
        2. Score = confidence * (1 + log(recall_count + 1)) * recency_factor
        3. Keep top `keep` (default: MAX_MEMORIES_PER_AGENT) by score
        4. Delete the rest

        Returns:
            Number of entries pruned
        """
        ...

    def _ensure_table(self) -> None:
        """Create agent_memories table if not exists."""
        ...

    def _append_to_md(self, entry: MemoryEntry) -> None:
        """Append entry to the agent's MEMORY.md file."""
        ...
```

### 4.2 Factory Function

```python
# src/agenticops/memory/__init__.py

from agenticops.memory.agent_memory import AgentMemory

_memory_cache: dict[str, AgentMemory] = {}


def get_agent_memory(agent_name: str) -> AgentMemory:
    """Get or create an AgentMemory instance for the given agent.

    Uses singleton pattern per agent_name.
    """
    if agent_name not in _memory_cache:
        from agenticops.config import settings
        db_path = settings.database_url.replace("sqlite:///", "")
        _memory_cache[agent_name] = AgentMemory(agent_name, db_path)
    return _memory_cache[agent_name]


# Convenience: pre-defined agent names matching agents/ module
AGENT_NAMES = [
    "main_agent",
    "scan_agent",
    "detect_agent",
    "rca_agent",
    "sre_agent",
    "executor_agent",
    "reporter_agent",
]
```

---

## 5. Integration Points

### 5.1 Agent Integration (Strands Tools)

Each agent gets memory tools added to its tool list:

```python
# src/agenticops/tools/memory_tools.py

from strands import tool
from agenticops.memory import get_agent_memory
from agenticops.memory.types import MemoryType


@tool
def remember_this(
    content: str,
    memory_type: str = "episodic",
    source: str = "",
) -> str:
    """Store a memory for future recall.

    Use this when you learn something important during an investigation:
    - A diagnosis pattern that worked
    - A fix that resolved an issue
    - A configuration detail worth remembering

    Args:
        content: What to remember (natural language)
        memory_type: episodic, procedural, or semantic
        source: What triggered this (e.g., "rca:issue-42")
    """
    # Agent name is resolved from the current execution context
    ...


@tool
def recall_memories(
    query: str,
    top_k: int = 5,
) -> str:
    """Search your memories for relevant past experiences.

    Use BEFORE starting any investigation to check if you've seen similar issues.

    Args:
        query: What to search for (e.g., "EKS pod OOM crash")
        top_k: Max results to return
    """
    ...
```

### 5.2 RCA Agent Example

```python
# In rca_agent.py — updated tool list
from agenticops.tools.memory_tools import remember_this, recall_memories

# Add to agent tools:
tools=[
    ...,
    remember_this,
    recall_memories,
]
```

### 5.3 Pipeline Integration

```python
# In pipeline stages — automatic memory capture

async def post_rca_memory_hook(rca_result, agent_memory):
    """After RCA completes, capture the result as memory."""
    await agent_memory.remember(
        content=f"RCA for {rca_result.resource}: {rca_result.root_cause}. "
                f"Fix: {rca_result.recommendation}. Confidence: {rca_result.confidence}",
        memory_type=MemoryType.EPISODIC,
        source=f"rca:issue-{rca_result.issue_id}",
        confidence=rca_result.confidence,
    )
```

### 5.4 Self-Governance Protocols (from Researcher's arc-* deep dive)

Critical patterns integrated into Memory System:

| Protocol | Implementation |
|----------|---------------|
| **WAL (Write-Ahead Log)** | `remember()` MUST be called BEFORE agent responds — ensures memory survives session interruption |
| **VBR (Verify Before Report)** | Executor: after fix, verify → then `remember(confidence=0.9)` → report "resolved" |
| **IKL (Infra Knowledge Log)** | Scan Agent: every discovered resource → `remember(type=SEMANTIC)` immediately |

### 5.5 Cross-Agent Knowledge Sharing

Agents do NOT read each other's memory directly. Instead:

```
RCA Agent completes investigation
    ↓
remember_this() → RCA Agent's memory (private)
    ↓
KnowledgeFlywheel.capture() → CaseStudy → KB (shared)
    ↓
Detect Agent queries KB → finds similar pattern
```

---

## 6. Memory Lifecycle

```
Event (alert/RCA/fix)
    ↓
remember() → SQLite + MEMORY.md + Embedding
    ↓
recall() → Semantic search (cosine sim) → Boost recall_count
    ↓
reflect() → Daily consolidation → Summary → Prune low-value
    ↓
prune() → Score = confidence × (1 + log(recalls)) × recency → Keep top N
```

### Confidence Decay

```python
def decayed_confidence(entry: MemoryEntry, now: datetime) -> float:
    """Confidence decays with time, boosted by recall frequency."""
    age_days = (now - entry.timestamp).days
    decay = 0.99 ** age_days  # ~37% after 100 days
    recall_boost = 1 + 0.1 * min(entry.recall_count, 10)
    return entry.confidence * decay * recall_boost
```

---

## 7. Consolidation Strategy

### Daily Reflect

Triggered by scheduler at end of day (or when CONSOLIDATION_THRESHOLD reached):

1. **Gather** today's episodic memories
2. **Cluster** similar memories (cosine sim > 0.85)
3. **Summarize** clusters via LLM:
   ```
   "Today I analyzed 5 incidents:
    - 3 were EKS-related (2 OOM, 1 node NotReady)
    - Pattern: resource limits consistently underprovisioned
    - Suggestion: add proactive memory monitoring watcher"
   ```
4. **Store** summary as REFLECTION type (never pruned)
5. **Prune** individual episodic entries that are now captured in reflection
6. **Update** MEMORY.md

### Memory Budget

| Agent | Max Entries | Reflection Retention | Prune Strategy |
|-------|------------|---------------------|----------------|
| rca_agent | 1000 | Forever | Low confidence + low recall + old |
| detect_agent | 500 | Forever | Same |
| sre_agent | 500 | Forever | Same |
| Others | 200 | Forever | Same |

---

## 8. Testing Requirements

### Unit Tests

```python
# tests/test_agent_memory.py

class TestAgentMemory:
    def test_remember_and_recall(self):
        """remember() → recall() returns the entry."""

    def test_recall_semantic_search(self):
        """Similar query finds related memories."""

    def test_recall_filters_by_type(self):
        """memory_type filter works."""

    def test_recall_filters_by_confidence(self):
        """min_confidence filter excludes low-confidence entries."""

    def test_recall_increments_recall_count(self):
        """recall() increments the recall_count on returned entries."""

    def test_prune_keeps_high_value(self):
        """High confidence + high recall entries survive pruning."""

    def test_prune_removes_old_low_value(self):
        """Old entries with low confidence and 0 recalls are pruned."""

    def test_prune_never_removes_reflections(self):
        """REFLECTION type entries are never pruned."""

    def test_memory_isolation(self):
        """Agent A's memory is invisible to Agent B."""

    def test_memory_md_append(self):
        """remember() appends to MEMORY.md file."""

    def test_consolidation_threshold(self):
        """Consolidation triggers after N entries."""

    def test_confidence_decay(self):
        """decayed_confidence decreases with age."""

    def test_null_embedding_fallback(self):
        """Works with NullEmbeddingClient (no vector search, only recency)."""
```

### Integration Tests

```python
class TestMemoryIntegration:
    def test_rca_agent_remembers_after_investigation(self):
        """RCA completion triggers memory capture."""

    def test_detect_agent_recalls_before_detection(self):
        """Detect agent queries memory before starting."""

    def test_cross_agent_sharing_via_kb(self):
        """Agent A's memory → KB CaseStudy → Agent B recalls via KB."""
```

---

## 9. Implementation Notes for Developer

### Priority Order

1. `types.py` — MemoryEntry + MemoryType (15 min)
2. `agent_memory.py` — remember() + recall() + prune() (2h)
3. `memory_tools.py` — Strands @tool wrappers (30 min)
4. `__init__.py` — Factory + agent name registry (15 min)
5. Agent integration — add tools to rca_agent.py first (30 min)
6. `consolidator.py` — reflect() with LLM summary (1h)
7. Tests — unit + integration (2h)
8. MEMORY.md file generation (30 min)

### Reuse Checklist

- ✅ `kb/vector_store.py` → VectorStore interface (DON'T create a new one)
- ✅ `kb/embeddings.py` → get_embedding_client() singleton
- ✅ `config.py` → settings.database_url for DB path
- ✅ `models.py` → get_db_session() for SQLAlchemy session (if needed)
- ❌ DON'T add new pip dependencies
- ❌ DON'T create a separate DB file — use existing agenticops.db

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| SQLite (not Redis/OpenSearch) | Zero new deps, consistent with existing KB |
| Separate table (not kb's case_vectors) | Different lifecycle, per-agent isolation |
| MEMORY.md alongside SQLite | Human readability + debugging |
| Confidence decay formula | Prevents stale memories from dominating |
| Cross-sharing via KB only | Clean boundaries, no hidden coupling |

---

*📐 Architect — Memory System Spec v1.0, 2026-03-10*
*Ready for Developer to implement via Claude Code*
