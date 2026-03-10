"""SOPAutoWriter — auto-generate/update SOPs from RCA results.

Connects to rca_learner → SkillGapDetector → SOP generation pipeline.
Reuses existing sop_upgrader.py for LLM-based generation.

Design: ADR-009 §9.3 (ported from agentic-aiops-mvp)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class SOPDraft:
    """Auto-generated SOP draft from RCA results."""

    title: str
    service: str
    alert_type: str = "unknown"
    root_cause: str = ""
    trigger: str = "new_pattern"  # new_pattern | better_fix | escalation_path
    diagnostic_steps: list[str] = field(default_factory=list)
    remediation_steps: list[str] = field(default_factory=list)
    evidence_summary: list[str] = field(default_factory=list)
    created_from_incident: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "draft"  # draft → active → stable → review_needed

    def to_markdown(self) -> str:
        """Render SOP as markdown."""
        lines = [
            "---",
            f"service: {self.service}",
            f"alert_type: {self.alert_type}",
            f"trigger: {self.trigger}",
            f"status: {self.status}",
            f"created: {self.created_at}",
            f"incident: {self.created_from_incident}",
            "---",
            f"# {self.title}",
            "",
            f"## Root Cause\n{self.root_cause}",
            "",
            "## Diagnosis Steps",
        ]
        for i, step in enumerate(self.diagnostic_steps, 1):
            lines.append(f"{i}. {step}")

        lines.append("\n## Remediation")
        for i, step in enumerate(self.remediation_steps, 1):
            lines.append(f"{i}. {step}")

        if self.evidence_summary:
            lines.append("\n## Evidence")
            for ev in self.evidence_summary:
                lines.append(f"- {ev}")

        return "\n".join(lines)


class SOPDeduplicator:
    """Prevent SOP knowledge base pollution via similarity check."""

    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, kb_search=None):
        self.kb_search = kb_search

    async def find_similar(self, root_cause: str, service: str) -> Optional[dict]:
        """Query KB for existing similar SOP."""
        if not self.kb_search:
            return None

        query = f"{root_cause} {service}"
        try:
            results = await self.kb_search.hybrid_search(query_text=query, top_k=5)
        except Exception as e:
            logger.warning("KB search failed during SOP dedup: %s", e)
            return None

        if results and hasattr(results[0], "score") and results[0].score > self.SIMILARITY_THRESHOLD:
            return {
                "sop_id": getattr(results[0], "metadata", {}).get("sop_id", ""),
                "similarity": results[0].score,
                "content": getattr(results[0], "content", ""),
                "action": "update",
            }
        return None


class SOPAutoWriter:
    """RCA completion → SOP auto-generation/update.

    Trigger conditions:
    - new_pattern: No matching SOP in KB
    - better_fix: Existing SOP fix steps incomplete
    - escalation_path: New escalation path discovered
    """

    def __init__(
        self,
        deduplicator: Optional[SOPDeduplicator] = None,
        sop_dir: Optional[str] = None,
    ):
        self.deduplicator = deduplicator or SOPDeduplicator()
        self.sop_dir = sop_dir

    def evaluate_trigger(
        self,
        existing_sop: Optional[dict],
        rca_result: dict,
        resolution_log: list[str],
    ) -> Optional[str]:
        """Determine which trigger condition is met."""
        if not existing_sop:
            return "new_pattern"

        existing_steps = existing_sop.get("content", "").count("\n")
        new_steps = len(resolution_log)
        if new_steps > existing_steps * 1.5 and new_steps >= 3:
            return "better_fix"

        escalation_keywords = ["escalat", "page", "on-call", "manager", "incident commander"]
        if any(kw in " ".join(resolution_log).lower() for kw in escalation_keywords):
            return "escalation_path"

        return None

    def build_sop_from_rca(
        self,
        rca_result: dict,
        resolution_log: list[str],
        evidence_chain: list[Any] = None,
        incident_id: str = "",
        trigger: str = "new_pattern",
    ) -> SOPDraft:
        """Build SOPDraft from RCA results (template-based, no LLM needed)."""
        service = rca_result.get("affected_service", rca_result.get("service", "unknown"))
        alert_type = rca_result.get("alert_type", "unknown")
        root_cause = rca_result.get("root_cause", "Unknown root cause")
        symptoms = rca_result.get("symptoms", [])
        recommendations = rca_result.get("recommendations", [])

        diag_steps = []
        if isinstance(symptoms, list):
            for s in symptoms:
                diag_steps.append(f"Verify symptom: {s}")
        diag_steps.append("Check relevant CloudWatch metrics")
        diag_steps.append("Review CloudTrail for recent changes")

        remediation = list(recommendations[:5]) if recommendations else list(resolution_log[:5])
        if not remediation:
            remediation = ["Investigate root cause", "Apply fix", "Verify and monitor"]

        evidence_summary = []
        if evidence_chain:
            for ev in evidence_chain[:5]:
                content = getattr(ev, "content", str(ev))
                evidence_summary.append(content[:150])

        return SOPDraft(
            title=f"{service.upper()} {alert_type} Recovery",
            service=service,
            alert_type=alert_type,
            root_cause=root_cause,
            trigger=trigger,
            diagnostic_steps=diag_steps,
            remediation_steps=remediation,
            evidence_summary=evidence_summary,
            created_from_incident=incident_id,
        )

    async def evaluate_and_write(
        self,
        rca_result: dict,
        resolution_log: list[str],
        evidence_chain: list[Any] = None,
        incident_id: str = "",
    ) -> Optional[SOPDraft]:
        """Evaluate whether to generate/update SOP, then do it."""
        root_cause = rca_result.get("root_cause", "")
        service = rca_result.get("affected_service", rca_result.get("service", ""))

        # 1. Dedup check
        try:
            existing = await self.deduplicator.find_similar(root_cause, service)
        except Exception as e:
            logger.warning("Dedup failed, treating as new: %s", e)
            existing = None

        # 2. Evaluate trigger
        trigger = self.evaluate_trigger(existing, rca_result, resolution_log)
        if not trigger:
            logger.debug("No SOP trigger for incident %s", incident_id)
            return None

        logger.info("SOP trigger: %s for %s (service=%s)", trigger, incident_id, service)

        # 3. Generate SOP
        sop = self.build_sop_from_rca(
            rca_result, resolution_log, evidence_chain, incident_id, trigger,
        )

        # 4. Store (local draft dir or S3 in production)
        if self.sop_dir:
            self._store_local(sop)

        return sop

    def _store_local(self, sop: SOPDraft) -> None:
        """Write SOP draft to local directory."""
        from pathlib import Path
        draft_dir = Path(self.sop_dir)
        draft_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{sop.service}_{sop.alert_type}_{sop.trigger}.md"
        (draft_dir / filename).write_text(sop.to_markdown())
        logger.info("SOP draft stored: %s", draft_dir / filename)
