"""ProactiveAgent — Memory-driven proactive operations agent.

Security: T0 (read-only). Never modifies infrastructure.
Output: ProactiveAlert → alert_pipeline → rca_agent chain.

Spec: PROACTIVE_AGENT_SPEC §5.1
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Optional

from agenticops.memory.agent_memory import AgentMemory
from agenticops.memory.types import MemoryType
from agenticops.proactive.pattern_watch import PatternWatch
from agenticops.proactive.risk_scorer import RiskScorer, RiskLevel, HealthIssue
from agenticops.proactive.predictive_alert import ProactiveAlert

logger = logging.getLogger(__name__)


class ProactiveAgent:
    """Memory-driven proactive operations agent.

    Heartbeat: Runs PatternWatch + RiskScorer on configurable interval.
    Output: ProactiveAlert → alert_pipeline → rca_agent chain.
    Safety: T0 locked, rate limited (max 5 alerts/hour).
    """

    MAX_ALERTS_PER_HOUR = 5
    DEFAULT_INTERVAL = 300  # 5 minutes

    def __init__(
        self,
        memory: AgentMemory,
        alert_callback: Optional[Any] = None,
        interval_seconds: int = DEFAULT_INTERVAL,
    ):
        self.memory = memory
        self.alert_callback = alert_callback  # async fn(ProactiveAlert)
        self.interval = interval_seconds
        self.pattern_watch = PatternWatch()
        self.risk_scorer = RiskScorer()
        self._running = False
        self._alert_history: deque[datetime] = deque(maxlen=100)

    async def start(self) -> None:
        """Start the proactive loop."""
        from agenticops.skills.agent_binding import bind_agent
        bind_agent("proactive_agent")  # T0 lock

        self._running = True
        logger.info("ProactiveAgent started (interval=%ds)", self.interval)

        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.error("ProactiveAgent cycle error: %s", e)
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        """Stop the proactive loop."""
        self._running = False
        logger.info("ProactiveAgent stopped")

    async def _cycle(self) -> list[ProactiveAlert]:
        """Single proactive cycle: scan → score → alert.

        Returns list of generated alerts (for testing).
        """
        # Rate limit check
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        recent_alerts = sum(1 for t in self._alert_history if t > hour_ago)
        if recent_alerts >= self.MAX_ALERTS_PER_HOUR:
            logger.debug("Rate limited: %d alerts in past hour", recent_alerts)
            return []

        # Scan for patterns
        patterns = await self.pattern_watch.scan(self.memory)
        if not patterns:
            return []

        generated = []
        for pattern in patterns:
            if recent_alerts + len(generated) >= self.MAX_ALERTS_PER_HOUR:
                break

            risk = self.risk_scorer.score(pattern)
            if risk >= RiskLevel.WARN:
                alert = ProactiveAlert.from_pattern(pattern, risk)
                generated.append(alert)
                self._alert_history.append(now)

                # Fire alert
                if self.alert_callback:
                    try:
                        await self.alert_callback(alert)
                    except Exception as e:
                        logger.warning("Alert callback failed: %s", e)

                # Remember the proactive action
                await self.memory.remember(
                    content=(
                        f"PROACTIVE_ALERT: {pattern.category}, "
                        f"risk={risk.name}, occurrences={pattern.occurrences}, "
                        f"score={pattern.score:.2f}"
                    ),
                    memory_type=MemoryType.EPISODIC,
                    source="proactive_agent",
                    confidence=pattern.score,
                )

                logger.info(
                    "ProactiveAlert generated: %s (risk=%s, score=%.2f)",
                    pattern.category, risk.name, pattern.score,
                )
            elif risk >= RiskLevel.NOTIFY:
                logger.info(
                    "ProactiveNotify: %s (risk=%s, score=%.2f) — below WARN threshold",
                    pattern.category, risk.name, pattern.score,
                )

        return generated

    @property
    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        """Get proactive agent statistics."""
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        return {
            "running": self._running,
            "interval": self.interval,
            "alerts_last_hour": sum(1 for t in self._alert_history if t > hour_ago),
            "max_alerts_per_hour": self.MAX_ALERTS_PER_HOUR,
        }
