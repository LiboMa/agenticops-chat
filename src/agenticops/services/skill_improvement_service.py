"""Skill improvement service — centralized logic for all self-improvement triggers.

Three trigger sources feed into the same draft-creation pipeline:
1. Manual — user explicitly requests improvement via Chat or Web Portal
2. Post-resolution — after a HealthIssue is resolved, analyze agent actions vs skills
3. Agent-detected — any agent flags a skill gap during its work

All improvements create drafts for human review (never auto-promote).
Uses the existing JSON-file improvement_store for persistence.
"""

from __future__ import annotations

import logging
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)


def trigger_skill_improvement(
    skill_name: str,
    gap_description: str,
    trigger: str = "manual",
    source: str = "system",
    source_issue_id: Optional[int] = None,
    source_agent: Optional[str] = None,
) -> dict:
    """Create a skill improvement record (pending) and return immediately.

    The actual LLM generation should be run separately via
    run_skill_improvement() in a background task.

    Args:
        skill_name: Name of the skill to improve.
        gap_description: What's missing or needs improvement.
        trigger: One of 'manual', 'post_resolution', 'agent_detected'.
        source: Origin of the request ('web', 'cli', 'agent', 'system').
        source_issue_id: HealthIssue ID that triggered this (if any).
        source_agent: Agent name that detected the gap (if any).

    Returns:
        Dict with record_id and pending status.
        On error, returns dict with 'error' key.
    """
    if not settings.skills_auto_improve_enabled:
        return {"error": "Skill auto-improvement is disabled"}

    from agenticops.skills.improvement_store import add_improvement

    extra_source = source
    if source_agent:
        extra_source = f"{source}:agent:{source_agent}"
    if source_issue_id:
        extra_source += f":issue:{source_issue_id}"

    rec = add_improvement(
        skill_name=skill_name,
        improvement=gap_description,
        source=extra_source,
        trigger=trigger,
    )

    return {
        "record_id": rec["id"],
        "skill_name": skill_name,
        "trigger": trigger,
        "status": "pending",
        "draft_path": "",
    }


def run_skill_improvement(
    record_id: str,
    skill_name: str,
    gap_description: str,
    source_agent: Optional[str] = None,
) -> dict:
    """Run the LLM improvement and update the record. Call from a background task."""
    from agenticops.skills.evolution import auto_improve_skill
    from agenticops.skills.improvement_store import update_improvement
    from agenticops.skills.loader import _invalidate_skills_cache

    result = auto_improve_skill(skill_name, gap_description)
    if "error" in result:
        update_improvement(record_id, "failed", result)
        return {"error": result["error"], "record_id": record_id}

    update_improvement(record_id, "completed", result)
    _invalidate_skills_cache()

    if settings.skills_improvement_notify:
        _notify_improvement(skill_name, gap_description, "manual", source_agent)

    return {
        "record_id": record_id,
        "skill_name": skill_name,
        "status": "completed",
        "draft_path": result.get("draft_path", ""),
    }


def analyze_skill_gaps(health_issue_id: int) -> list[dict]:
    """Analyze a resolved issue to find skill gaps.

    Looks at AgentLog entries for the issue's trace, identifies which skills
    were activated, and checks for gaps (errors, missing coverage, long
    durations suggesting the agent struggled).

    Args:
        health_issue_id: ID of the resolved HealthIssue.

    Returns:
        List of dicts with keys: skill_name, gap_description, confidence.
    """
    from agenticops.models import AgentLog, HealthIssue, get_db_session

    gaps: list[dict] = []

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue or issue.status != "resolved":
            return gaps

        trace_id = issue.trace_id
        if not trace_id:
            return gaps

        logs = (
            session.query(AgentLog)
            .filter(AgentLog.trace_id == trace_id)
            .order_by(AgentLog.created_at)
            .all()
        )

        if not logs:
            return gaps

        # Collect signals
        activated_skills: set[str] = set()
        error_agents: list[str] = []
        slow_agents: list[tuple[str, int]] = []

        for log in logs:
            if "activate_skill" in (log.action or ""):
                summary = log.output_summary or ""
                if "activated_skill" in summary:
                    for part in summary.split('"'):
                        if part and not part.startswith("<") and part not in ("activated_skill", "name="):
                            activated_skills.add(part)
                            break

            if log.status == "error":
                error_agents.append(log.agent_name)

            if log.duration_ms > 60_000:
                slow_agents.append((log.agent_name, log.duration_ms))

        # Pattern 1: Repeated agent errors → skill gap
        agent_counts: dict[str, int] = {}
        for agent in error_agents:
            agent_counts[agent] = agent_counts.get(agent, 0) + 1
        for agent, count in agent_counts.items():
            if count >= 2:
                skill = _agent_to_skill(agent)
                if skill:
                    gaps.append({
                        "skill_name": skill,
                        "gap_description": (
                            f"Agent '{agent}' encountered {count} errors while resolving "
                            f"issue #{health_issue_id} ({issue.title[:80]}). "
                            f"Resource type: {issue.resource_type}, region: {issue.region}."
                        ),
                        "confidence": min(0.5 + count * 0.1, 0.9),
                    })

        # Pattern 2: Expected skill not activated
        resource_skill = _resource_type_to_skill(issue.resource_type or "")
        if resource_skill and resource_skill not in activated_skills:
            gaps.append({
                "skill_name": resource_skill,
                "gap_description": (
                    f"Skill '{resource_skill}' was not activated during resolution of "
                    f"issue #{health_issue_id} ({issue.title[:80]}), but resource type "
                    f"'{issue.resource_type}' typically requires it."
                ),
                "confidence": 0.4,
            })

        # Pattern 3: Slow resolution → incomplete decision trees
        for agent, ms in slow_agents:
            skill = _agent_to_skill(agent)
            if skill:
                gaps.append({
                    "skill_name": skill,
                    "gap_description": (
                        f"Agent '{agent}' took {ms // 1000}s during resolution of "
                        f"issue #{health_issue_id}, suggesting incomplete procedures "
                        f"for {issue.resource_type}."
                    ),
                    "confidence": 0.3,
                })

    return gaps


# ── Internal helpers ──────────────────────────────────────────────────


def _notify_improvement(
    skill_name: str, gap: str, trigger: str, source_agent: Optional[str]
) -> None:
    """Fire-and-forget notification about a new skill improvement draft."""
    try:
        from agenticops.services.notification_service import notify_pipeline_event

        source = f" (agent: {source_agent})" if source_agent else ""
        notify_pipeline_event(
            subject=f"Skill improvement draft: {skill_name}",
            body=(
                f"A skill improvement draft has been created for **{skill_name}**.\n\n"
                f"**Trigger:** {trigger}{source}\n"
                f"**Gap:** {gap[:300]}\n\n"
                f"Review and promote/reject in the Skills page."
            ),
            severity="low",
        )
    except Exception:
        logger.debug("Skill improvement notification skipped: %s", skill_name)


_AGENT_SKILL_MAP = {
    "rca": "monitoring",
    "sre": "linux-admin",
    "detect": "monitoring",
    "scan": "aws-compute",
    "executor": "linux-admin",
    "reporter": "log-analysis",
}

_RESOURCE_SKILL_MAP = {
    "ec2": "aws-compute",
    "instance": "aws-compute",
    "lambda": "aws-compute",
    "rds": "database-admin",
    "dynamodb": "database-admin",
    "aurora": "database-admin",
    "s3": "aws-storage",
    "ebs": "aws-storage",
    "efs": "aws-storage",
    "eks": "kubernetes-admin",
    "k8s": "kubernetes-admin",
    "pod": "kubernetes-admin",
    "elasticsearch": "elasticsearch",
    "opensearch": "elasticsearch",
    "vpc": "network-engineer",
    "elb": "network-engineer",
    "alb": "network-engineer",
    "nlb": "network-engineer",
}


def _agent_to_skill(agent_name: str) -> Optional[str]:
    return _AGENT_SKILL_MAP.get(agent_name)


def _resource_type_to_skill(resource_type: str) -> Optional[str]:
    rt = resource_type.lower()
    for key, skill in _RESOURCE_SKILL_MAP.items():
        if key in rt:
            return skill
    return None
