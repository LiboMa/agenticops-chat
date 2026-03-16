"""Post-RCA Learning — self-verification + revision-first skill updates.

Implements spec §3.5 (LearnAct revision-first pattern):
- Store RCA outcomes as memory
- Revise existing Skills before creating new ones
- Periodic reflection (Generative Agents pattern)
"""

import asyncio
import logging
from datetime import datetime

from agenticops.analyze.deep_rca import DeepRCAResult
from agenticops.memory import MemoryType, get_agent_memory
from agenticops.utils.timeutils import utc_now

logger = logging.getLogger(__name__)


class RCALearner:
    """Async post-RCA learning — fire-and-forget after returning result."""

    AGENT_NAME = "rca_agent"
    REFLECT_THRESHOLD = 5  # Reflect after N incidents/day

    def __init__(self):
        self.memory = get_agent_memory(self.AGENT_NAME)

    async def learn(self, result: DeepRCAResult) -> dict:
        """Post-RCA learning pipeline.

        1. Remember outcome (already done by WAL, but add patterns)
        2. Revision-first skill update (LearnAct)
        3. Periodic reflection (Generative Agents)

        Returns summary dict of what was learned.
        """
        summary = {
            "patterns_stored": 0,
            "skill_action": "none",  # "revised" | "created" | "none"
            "reflected": False,
        }

        # 1. Extract and store patterns
        patterns = self._extract_patterns(result)
        for pattern in patterns:
            await self.memory.remember(
                content=pattern,
                memory_type=MemoryType.PROCEDURAL,
                source=f"rca_learner:{result.analysis.root_cause[:50]}",
                confidence=result.analysis.confidence_score,
            )
            summary["patterns_stored"] += 1

        # 2. Revision-first skill update
        if result.analysis.confidence_score >= 0.7:
            skill_action = await self._update_skills(result)
            summary["skill_action"] = skill_action

        # 3. Periodic reflection
        incident_count = await self._incident_count_today()
        if incident_count >= self.REFLECT_THRESHOLD:
            await self.memory.reflect()
            summary["reflected"] = True
            logger.info(
                "RCA Learner: reflected after %d incidents today", incident_count
            )

        return summary

    def _extract_patterns(self, result: DeepRCAResult) -> list[str]:
        """Extract reusable patterns from RCA result."""
        patterns = []

        # Pattern from contributing factors → root cause
        if result.analysis.contributing_factors:
            factors = ", ".join(result.analysis.contributing_factors[:3])
            patterns.append(
                f"PATTERN: When {factors} → likely root cause: "
                f"{result.analysis.root_cause[:150]}"
            )

        # Pattern from recommendations
        if result.analysis.recommendations:
            rec = result.analysis.recommendations[0]
            patterns.append(
                f"FIX: For '{result.analysis.root_cause[:100]}' → {rec[:150]}"
            )

        # Pattern from evidence chain
        high_value_evidence = [
            e for e in result.evidence_chain if e.confidence_delta > 0.1
        ]
        for ev in high_value_evidence[:2]:
            patterns.append(
                f"EVIDENCE: {ev.source} finding '{ev.content[:100]}' "
                f"strongly correlated with root cause (Δ={ev.confidence_delta:.2f})"
            )

        return patterns

    async def _update_skills(self, result: DeepRCAResult) -> str:
        """Revision-first skill update (LearnAct pattern).

        Try to revise existing skill before creating a new one.
        Uses SkillGapDetector for gap analysis + evolution.create_draft_skill for creation.
        """
        try:
            from agenticops.skills.iteration import gap_detector as _gd

            detector = _gd.SkillGapDetector()
            root_cause_category = self._categorize_root_cause(
                result.analysis.root_cause
            )

            # Use SkillGapDetector to analyze the incident
            rca_dict = {
                "confidence": result.analysis.confidence_score,
                "affected_service": root_cause_category,
                "detection_source": "rca_agent",
                "similar_incident_count": len(result.memory_hits),
            }
            gap = detector.analyze_incident(
                incident=getattr(result, "anomaly_title", root_cause_category),
                rca_result=rca_dict,
                resolution_log=[
                    r[:80] for r in (result.analysis.recommendations or [])
                ],
            )

            if gap:
                logger.info("RCA Learner: gap detected — %s", gap.gap_type)
                # Record gap in memory
                await self.memory.remember(
                    content=(
                        f"SKILL_GAP ({gap.gap_type}): {gap.description}. "
                        f"Root cause: '{result.analysis.root_cause[:100]}'. "
                        f"Domain: {gap.suggested_skill_domain}"
                    ),
                    memory_type=MemoryType.SEMANTIC,
                    source=f"skill_gap:{gap.gap_type}",
                    confidence=result.analysis.confidence_score,
                )

                # Create draft skill if confidence is high enough
                if self._should_create_skill(result):
                    try:
                        from agenticops.skills.evolution import create_draft_skill

                        skill_content = (
                            f"# {root_cause_category} Troubleshooting\n\n"
                            f"## Root Cause Pattern\n{result.analysis.root_cause}\n\n"
                            f"## Evidence\n"
                            + "\n".join(
                                f"- {e.content[:100]}" for e in result.evidence_chain[:5]
                            )
                            + f"\n\n## Recommendations\n"
                            + "\n".join(
                                f"- {r}" for r in (result.analysis.recommendations or [])
                            )
                        )
                        create_draft_skill(
                            name=f"auto_{root_cause_category}_{gap.gap_type}",
                            description=f"Auto-generated skill for {root_cause_category} ({gap.gap_type})",
                            content=skill_content,
                        )
                        logger.info("Draft skill created for %s", root_cause_category)
                    except Exception as e:
                        logger.warning("Draft skill creation failed: %s", e)

                return "created"
            else:
                # No gap — existing skills cover this pattern, record revision note
                await self.memory.remember(
                    content=(
                        f"SKILL_OK: Existing skills cover '{root_cause_category}'. "
                        f"Confidence: {result.analysis.confidence_score:.2f}"
                    ),
                    memory_type=MemoryType.SEMANTIC,
                    source="skill_coverage_ok",
                    confidence=result.analysis.confidence_score,
                )
                return "revised"

        except ImportError:
            logger.debug("SkillGapDetector not available, skipping skill update")
        except Exception as e:
            logger.warning("Skill update failed: %s", e)

        return "none"

    def _categorize_root_cause(self, root_cause: str) -> str:
        """Categorize root cause into a skill category."""
        categories = {
            "oom": ["oom", "out of memory", "memory limit", "killed"],
            "cpu": ["cpu", "throttle", "high utilization"],
            "network": ["timeout", "connection refused", "dns", "network"],
            "storage": ["disk", "ebs", "volume", "iops", "storage"],
            "permission": ["permission", "iam", "access denied", "unauthorized"],
            "config": ["configuration", "misconfigured", "wrong setting"],
            "scaling": ["capacity", "scaling", "autoscal", "instance count"],
            "dependency": ["downstream", "upstream", "dependency", "cascade"],
        }
        lower = root_cause.lower()
        for category, keywords in categories.items():
            if any(kw in lower for kw in keywords):
                return category
        return "general"

    def _should_create_skill(self, result: DeepRCAResult) -> bool:
        """Determine if a new skill should be created."""
        # Only create skill for high-confidence, novel patterns
        return (
            result.analysis.confidence_score >= 0.8
            and not result.is_known_pattern
            and result.iterations >= 2  # Required investigation
        )

    async def _incident_count_today(self) -> int:
        """Count today's incidents from memory."""
        recent = await self.memory.recall_recent(limit=50)
        today = utc_now().strftime("%Y-%m-%d")
        return sum(
            1
            for m in recent
            if m.timestamp.strftime("%Y-%m-%d") == today
            and m.source.startswith("deep_rca:")
        )
