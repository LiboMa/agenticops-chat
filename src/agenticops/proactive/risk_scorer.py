"""RiskScorer — decision engine for proactive alerts.

Spec: PROACTIVE_AGENT_SPEC §4.3
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import List, Any

from .pattern_watch import PatternAlert

logger = logging.getLogger(__name__)


class RiskLevel(enum.IntEnum):
    """Risk levels for proactive alerts."""
    IGNORE = 0
    NOTIFY = 1
    WARN = 2
    ESCALATE = 3

    def to_severity(self) -> str:
        """Map to StructuredAlert severity."""
        return {
            RiskLevel.IGNORE: "low",
            RiskLevel.NOTIFY: "low",
            RiskLevel.WARN: "medium",
            RiskLevel.ESCALATE: "high",
        }.get(self, "low")


@dataclass
class HealthIssue:
    """A detected health degradation."""
    area: str
    description: str
    severity: float = 0.5  # 0-1


class RiskScorer:
    """Score risk and decide action level.

    Confidence Ladder (Architect + Researcher consensus):
    - NOTIFY (≥0.3): Log + notify channel
    - WARN (≥0.65): Create ProactiveAlert → trigger RCA evaluation
    - ESCALATE (≥0.85): Escalate to SRE agent (still read-only)
    """

    NOTIFY_THRESHOLD = 0.3
    WARN_THRESHOLD = 0.65
    ESCALATE_THRESHOLD = 0.85

    def score(
        self,
        pattern: PatternAlert,
        health: List[HealthIssue] | None = None,
    ) -> RiskLevel:
        """Combine pattern frequency + current health into risk level."""
        base = pattern.score
        health = health or []

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
