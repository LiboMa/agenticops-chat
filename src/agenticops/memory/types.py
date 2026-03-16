"""Memory system data types for ClawOps per-agent memory."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from agenticops.utils.timeutils import utc_now


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
    timestamp: datetime = field(default_factory=utc_now)
    source: str = ""                      # What triggered this memory (e.g., "rca:issue-42")
    confidence: float = 1.0               # 0.0-1.0, decays over time
    recall_count: int = 0                 # How often this memory was retrieved
    id: Optional[int] = None              # DB primary key (set after insert)

    @property
    def memory_id(self) -> str:
        """Unique ID: agent_name:timestamp_iso."""
        return f"{self.agent_name}:{self.timestamp.isoformat()}"


def decayed_confidence(entry: MemoryEntry, now: Optional[datetime] = None) -> float:
    """Confidence decays with time, boosted by recall frequency.

    ~37% after 100 days with no recalls. Recall boosts up to 2x.
    """
    if now is None:
        now = utc_now()
    age_days = max(0, (now - entry.timestamp).days)
    decay = 0.99 ** age_days
    recall_boost = 1 + 0.1 * min(entry.recall_count, 10)
    return entry.confidence * decay * recall_boost
