"""PatternWatch — detect recurring incident patterns from agent memory.

Spec: PROACTIVE_AGENT_SPEC §4.1
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, List

logger = logging.getLogger(__name__)


@dataclass
class PatternAlert:
    """Detected recurring pattern from memory."""

    category: str
    occurrences: int
    score: float
    recent_entries: list[Any] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.category}: {self.occurrences}x (score={self.score:.2f})"


# Root cause category keywords (aligned with rca_learner._categorize_root_cause)
_CATEGORY_KEYWORDS = {
    "oom": ["oom", "out of memory", "memory limit", "killed", "memory leak"],
    "cpu": ["cpu", "throttle", "high utilization", "cpu spike"],
    "network": ["timeout", "connection refused", "dns", "network", "latency"],
    "storage": ["disk", "ebs", "volume", "iops", "storage", "disk full"],
    "permission": ["permission", "iam", "access denied", "unauthorized"],
    "config": ["configuration", "misconfigured", "wrong setting", "config"],
    "scaling": ["capacity", "scaling", "autoscal", "instance count"],
    "dependency": ["downstream", "upstream", "dependency", "cascade"],
}


class PatternWatch:
    """Detect recurring incident patterns from agent memory.

    Algorithm:
    1. Recall recent episodic + semantic memories (past N days)
    2. Group by root_cause_category
    3. If count >= RECURRENCE_THRESHOLD → generate PatternAlert
    4. Score by frequency * recency * avg_confidence
    """

    RECURRENCE_THRESHOLD = 3
    RECURRENCE_WINDOW_DAYS = 7
    CONFIDENCE_DECAY = 0.95  # Per-day decay

    async def scan(self, memory: Any) -> List[PatternAlert]:
        """Scan memory for recurring patterns."""
        try:
            recent = await memory.recall(
                "recurring incidents patterns failures errors",
                top_k=50,
                min_confidence=0.3,
            )
        except Exception as e:
            logger.warning("PatternWatch scan failed: %s", e)
            return []

        if not recent:
            return []

        # Group by category
        categories: dict[str, list[Any]] = {}
        for entry in recent:
            cat = self._extract_category(entry)
            if cat:
                categories.setdefault(cat, []).append(entry)

        # Generate alerts for recurring patterns
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

    def _extract_category(self, entry: Any) -> str:
        """Extract root cause category from a memory entry."""
        content = getattr(entry, "content", str(entry)).lower()

        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in content for kw in keywords):
                return category
        return ""

    def _score_pattern(self, entries: list[Any]) -> float:
        """Score a pattern by frequency * recency * confidence."""
        if not entries:
            return 0.0

        now = datetime.utcnow()
        total_score = 0.0

        for entry in entries:
            # Confidence
            confidence = getattr(entry, "confidence", 0.5)

            # Recency decay
            created = getattr(entry, "created_at", None)
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except (ValueError, TypeError):
                    created = now
            elif not isinstance(created, datetime):
                created = now

            age_days = max(0, (now - created).days)
            recency = self.CONFIDENCE_DECAY ** age_days

            total_score += confidence * recency

        # Normalize: higher frequency = higher score, capped at 1.0
        frequency_factor = min(1.0, len(entries) / 10.0)
        avg_score = total_score / len(entries)

        return min(1.0, avg_score * (1 + frequency_factor))
