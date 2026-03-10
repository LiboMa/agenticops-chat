"""SkillGapDetector — analyze incidents to detect Skills coverage gaps.

Design: ADR-009 §8.2
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class SkillGap:
    """Detected gap in Skills coverage."""

    gap_type: Literal[
        "novel_tool_usage",     # SRE used tools not covered by any Skill
        "detection_miss",       # Existing detection rules missed this incident
        "repeated_manual",      # Same manual steps repeated ≥3 times
        "low_confidence",       # Existing Skill's confidence score too low
    ]
    incident_id: str = ""
    suggested_skill_domain: str = ""
    uncovered_commands: list[str] = field(default_factory=list)
    repeat_count: int = 0
    suggested_action: str = ""
    description: str = ""

    @property
    def commands_hash(self) -> str:
        """Hash of uncovered commands for dedup."""
        raw = ":".join(sorted(self.uncovered_commands))
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "gap_type": self.gap_type,
            "incident_id": self.incident_id,
            "suggested_skill_domain": self.suggested_skill_domain,
            "uncovered_commands": self.uncovered_commands,
            "repeat_count": self.repeat_count,
            "suggested_action": self.suggested_action,
            "description": self.description,
        }


# Commands covered by existing Skills
_KNOWN_SKILL_COMMANDS = {
    "kubernetes": {"kubectl", "helm", "kubectx", "kubens", "k9s"},
    "linux_admin": {"ls", "grep", "awk", "sed", "top", "ps", "netstat", "lsof",
                    "vmstat", "iostat", "df", "du", "tail", "head", "cat", "find",
                    "systemctl", "journalctl", "dmesg"},
    "network_engineer": {"ping", "traceroute", "nslookup", "dig", "tcpdump",
                         "iptables", "ss", "ip", "curl", "wget", "nmap", "mtr"},
    "database_admin": {"mysql", "psql", "redis-cli", "mongo", "mongosh"},
    "storage": {"aws s3", "s3cmd", "rclone"},
    "log_analysis": {"grep", "awk", "jq", "cloudwatch"},
}

# Flatten for quick lookup
_ALL_KNOWN_COMMANDS: set[str] = set()
for cmds in _KNOWN_SKILL_COMMANDS.values():
    _ALL_KNOWN_COMMANDS.update(cmds)


def _infer_domain(commands: list[str]) -> str:
    """Infer which Skill domain the commands belong to."""
    scores: dict[str, int] = {}
    for cmd in commands:
        cmd_lower = cmd.lower().split()[0] if cmd else ""
        for domain, domain_cmds in _KNOWN_SKILL_COMMANDS.items():
            if cmd_lower in domain_cmds:
                scores[domain] = scores.get(domain, 0) + 1
    if scores:
        return max(scores, key=scores.get)
    return "general"


class SkillGapDetector:
    """Analyze resolved incidents to detect Skills coverage gaps.

    Trigger conditions (ADR-009 §8.2):
    - novel_tool_usage: SRE used commands not in any Skill
    - detection_miss: Existing rules missed this pattern
    - repeated_manual: Same fix applied ≥3 times manually
    - low_confidence: Skill's resolution confidence too low
    """

    REPEAT_THRESHOLD = 3
    LOW_CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, skill_registry: Optional[Any] = None, incident_store: Optional[Any] = None):
        self.skill_registry = skill_registry
        self.incident_store = incident_store

    def analyze_incident(
        self,
        incident: Any,
        rca_result: dict,
        resolution_log: Optional[list[str]] = None,
    ) -> Optional[SkillGap]:
        """Analyze a resolved incident for Skills coverage gaps.

        Args:
            incident: Incident record.
            rca_result: RCA analysis results.
            resolution_log: Commands/steps used during resolution.

        Returns:
            SkillGap if gap detected, None otherwise.
        """
        incident_id = getattr(incident, "incident_id", str(incident))
        resolution_log = resolution_log or []

        # Check 1: Novel tool usage
        gap = self._check_novel_tools(incident_id, resolution_log)
        if gap:
            return gap

        # Check 2: Repeated manual (same pattern ≥3 times)
        gap = self._check_repeated_manual(incident_id, rca_result)
        if gap:
            return gap

        # Check 3: Detection miss
        gap = self._check_detection_miss(incident_id, rca_result)
        if gap:
            return gap

        # Check 4: Low confidence
        gap = self._check_low_confidence(incident_id, rca_result)
        if gap:
            return gap

        return None

    def _check_novel_tools(self, incident_id: str, resolution_log: list[str]) -> Optional[SkillGap]:
        """Check if resolution used commands not covered by existing Skills."""
        uncovered = []
        for step in resolution_log:
            # Extract first word as command
            cmd = step.strip().split()[0] if step.strip() else ""
            if cmd and cmd.lower() not in _ALL_KNOWN_COMMANDS:
                uncovered.append(cmd)

        if uncovered:
            domain = _infer_domain(uncovered)
            logger.info("Novel tools detected: %s (domain=%s)", uncovered, domain)
            return SkillGap(
                gap_type="novel_tool_usage",
                uncovered_commands=uncovered,
                suggested_skill_domain=domain,
                incident_id=incident_id,
                description=f"Uncovered commands: {', '.join(uncovered)}",
            )
        return None

    def _check_repeated_manual(self, incident_id: str, rca_result: dict) -> Optional[SkillGap]:
        """Check if this incident pattern has been manually fixed ≥3 times."""
        repeat_count = rca_result.get("similar_incident_count", 0)
        if repeat_count >= self.REPEAT_THRESHOLD:
            service = rca_result.get("affected_service", rca_result.get("service", "unknown"))
            return SkillGap(
                gap_type="repeated_manual",
                repeat_count=repeat_count,
                suggested_action="create_runbook_skill",
                incident_id=incident_id,
                suggested_skill_domain=service,
                description=f"Manual fix repeated {repeat_count} times",
            )
        return None

    def _check_detection_miss(self, incident_id: str, rca_result: dict) -> Optional[SkillGap]:
        """Check if this incident was not detected by existing rules."""
        detection_source = rca_result.get("detection_source", "")
        if detection_source in ("manual", "user_report", ""):
            service = rca_result.get("affected_service", rca_result.get("service", "unknown"))
            alert_type = rca_result.get("alert_type", "unknown")
            return SkillGap(
                gap_type="detection_miss",
                incident_id=incident_id,
                suggested_skill_domain=service,
                suggested_action="create_detection_rule",
                description=f"No automated detection for {alert_type} on {service}",
            )
        return None

    def _check_low_confidence(self, incident_id: str, rca_result: dict) -> Optional[SkillGap]:
        """Check if RCA confidence was too low."""
        confidence = rca_result.get("confidence", 1.0)
        if isinstance(confidence, (int, float)) and confidence < self.LOW_CONFIDENCE_THRESHOLD:
            service = rca_result.get("affected_service", rca_result.get("service", "unknown"))
            return SkillGap(
                gap_type="low_confidence",
                incident_id=incident_id,
                suggested_skill_domain=service,
                description=f"RCA confidence too low: {confidence:.2f}",
            )
        return None
