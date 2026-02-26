"""RAG Pipeline — automated SOP generation and upgrade from resolved incidents.

When a HealthIssue is resolved (detect → RCA → fix → execute → verify),
this pipeline:
1. Extracts case data from the resolved issue + RCA + FixPlan
2. Searches for matching existing SOPs
3. Generates a new SOP or upgrades an existing one via LLM
4. Re-embeds the SOP for future vector search
5. Validates the knowledge base update

Reuses existing infrastructure from kb_tools.py (search, embed, write).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from agenticops.config import settings
from agenticops.pipeline.sop_identifier import SOPMatch, identify_matching_sop
from agenticops.pipeline.sop_upgrader import generate_new_sop, upgrade_existing_sop

logger = logging.getLogger(__name__)


@dataclass
class RAGPipelineResult:
    """Result of a RAG pipeline run."""

    health_issue_id: int
    success: bool
    action: str  # "created" | "upgraded" | "skipped" | "failed"
    sop_path: Optional[str] = None
    sop_filename: Optional[str] = None
    similarity_score: Optional[float] = None
    embed_status: str = ""
    validation_passed: bool = False
    error: Optional[str] = None
    duration_ms: int = 0
    steps: list[dict] = field(default_factory=list)


def run_rag_pipeline(health_issue_id: int) -> RAGPipelineResult:
    """Run the full RAG pipeline for a resolved HealthIssue.

    End-to-end: extract → match → generate/upgrade → embed → validate.

    Args:
        health_issue_id: The resolved HealthIssue ID.

    Returns:
        RAGPipelineResult with action taken, SOP path, and status.
    """
    if not settings.rag_pipeline_enabled:
        return RAGPipelineResult(
            health_issue_id=health_issue_id,
            success=False,
            action="skipped",
            error="RAG pipeline is disabled (AIOPS_RAG_PIPELINE_ENABLED=false)",
        )

    start = datetime.utcnow()
    result = RAGPipelineResult(
        health_issue_id=health_issue_id,
        success=False,
        action="failed",
    )

    try:
        # Step 1: Extract case data
        case_data = _extract_case_data(health_issue_id)
        if case_data is None:
            result.error = f"HealthIssue #{health_issue_id} not found, has no RCA, or is not resolved."
            result.steps.append({"step": "extract", "status": "failed", "error": result.error})
            return result
        result.steps.append({"step": "extract", "status": "ok", "resource_type": case_data["resource_type"]})

        # Step 2: Match against existing SOPs
        match = identify_matching_sop(
            resource_type=case_data["resource_type"],
            issue_pattern=case_data["issue_pattern"],
            severity=case_data.get("severity", ""),
        )
        result.similarity_score = match.similarity_score if match else 0.0
        result.steps.append({
            "step": "match",
            "status": "found" if match else "no_match",
            "score": result.similarity_score,
            "sop": match.filename if match else None,
        })

        # Step 3: Generate or upgrade SOP
        if match:
            sop_content = upgrade_existing_sop(match.content, case_data)
            sop_filename = match.filename
            sop_path = match.sop_path
            result.action = "upgraded"
        else:
            sop_content = generate_new_sop(case_data)
            sop_filename = _generate_sop_filename(case_data)
            sop_path = str(settings.sops_dir / sop_filename)
            result.action = "created"

        result.steps.append({"step": "generate", "status": "ok", "action": result.action, "filename": sop_filename})

        # Step 4: Write SOP and re-embed
        settings.ensure_dirs()
        Path(sop_path).write_text(sop_content)
        result.sop_path = sop_path
        result.sop_filename = sop_filename

        embed_status = _embed_sop(sop_content, sop_filename)
        result.embed_status = embed_status
        result.steps.append({"step": "embed", "status": "ok", "detail": embed_status})

        # Step 5: Validate
        validation_ok = _validate_sop_searchable(
            case_data["resource_type"],
            case_data["issue_pattern"],
            sop_filename,
        )
        result.validation_passed = validation_ok
        result.steps.append({"step": "validate", "status": "ok" if validation_ok else "warning"})

        result.success = True

    except Exception as e:
        logger.exception("RAG pipeline failed for HealthIssue #%d", health_issue_id)
        result.error = str(e)
        result.steps.append({"step": "error", "status": "failed", "error": str(e)})

    elapsed = (datetime.utcnow() - start).total_seconds()
    result.duration_ms = int(elapsed * 1000)
    return result


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _extract_case_data(health_issue_id: int) -> Optional[dict]:
    """Extract structured case data from a resolved HealthIssue + RCA + FixPlan.

    Returns dict with: resource_type, issue_pattern, severity, title, symptoms,
    root_cause, fix_steps, verification_steps, rollback_plan, prevention.
    """
    from agenticops.models import FixPlan, HealthIssue, RCAResult, get_db_session
    from agenticops.tools.kb_tools import _infer_resource_type

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return None

        rca = (
            session.query(RCAResult)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if not rca:
            return None

        # Get fix plan if available
        fix_plan = (
            session.query(FixPlan)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(FixPlan.created_at.desc())
            .first()
        )

        resource_type = _infer_resource_type(issue.resource_id or "")

        # Build issue pattern from title + description
        issue_pattern = issue.title or ""
        if issue.description:
            issue_pattern += " " + issue.description[:200]

        case_data = {
            "resource_type": resource_type,
            "issue_pattern": issue_pattern.strip(),
            "severity": issue.severity or "medium",
            "title": issue.title or "Untitled Issue",
            "symptoms": issue.description or "",
            "root_cause": rca.root_cause or "",
            "confidence": rca.confidence,
            "contributing_factors": rca.contributing_factors or "",
            "recommendations": rca.recommendations or "",
            "fix_risk_level": rca.fix_risk_level or "",
            "sop_used": rca.sop_used or "",
        }

        if fix_plan:
            case_data["fix_steps"] = fix_plan.steps or ""
            case_data["rollback_plan"] = fix_plan.rollback_plan or ""
            case_data["pre_checks"] = fix_plan.pre_checks or ""
            case_data["post_checks"] = fix_plan.post_checks or ""
            case_data["verification_steps"] = fix_plan.post_checks or ""
            case_data["estimated_impact"] = fix_plan.estimated_impact or ""

        return case_data


def _embed_sop(sop_content: str, filename: str) -> str:
    """Embed the SOP content and index for vector search.

    Reuses the embedding infrastructure from kb_tools.
    """
    try:
        from agenticops.kb.embeddings import get_embedding_client
        from agenticops.kb.vector_store import VectorRecord, get_vector_store
        from agenticops.tools.kb_tools import _parse_frontmatter

        metadata, body = _parse_frontmatter(sop_content)
        resource_type = str(metadata.get("resource_type", "Unknown")).upper()
        issue_pattern = str(metadata.get("issue_pattern", ""))

        client = get_embedding_client()
        if client.dimension == 0:
            return "Embeddings disabled."

        store = get_vector_store()
        case_id = Path(filename).stem
        indexed = 0

        # Embed the symptoms/issue pattern as "symptom" field
        symptom_text = issue_pattern + " " + body[:500]
        vec = client.embed(symptom_text.strip())
        if vec is not None:
            store.upsert(VectorRecord(
                case_id=case_id,
                field_name="symptom",
                vector=vec,
                resource_type=resource_type,
                metadata={"type": "sop", "filename": filename},
            ))
            indexed += 1

        # Embed root_cause section for cross-field search
        root_cause_text = _extract_section(body, "Root Cause", "Diagnosis")
        if root_cause_text:
            rc_vec = client.embed(root_cause_text.strip())
            if rc_vec is not None:
                store.upsert(VectorRecord(
                    case_id=case_id,
                    field_name="root_cause",
                    vector=rc_vec,
                    resource_type=resource_type,
                    metadata={"type": "sop", "filename": filename},
                ))
                indexed += 1

        return f"Indexed {indexed} vector(s) for SOP '{filename}'."
    except Exception as e:
        logger.warning("SOP embedding failed for %s: %s", filename, e)
        return f"Embedding skipped: {e}"


def _validate_sop_searchable(
    resource_type: str,
    issue_pattern: str,
    expected_filename: str,
) -> bool:
    """Validate the SOP is discoverable via search.

    Searches for the original issue pattern and checks if the new/updated
    SOP appears in results.
    """
    try:
        from agenticops.tools.kb_tools import _keyword_search_sops

        matches = _keyword_search_sops(resource_type, issue_pattern)
        for m in matches:
            if m["file"] == expected_filename:
                return True

        # Also try vector search
        try:
            from agenticops.kb.search import hybrid_search

            results = hybrid_search(
                query_text=issue_pattern,
                resource_type=resource_type,
                search_dir=settings.sops_dir,
                field_name="symptom",
                top_k=5,
            )
            for r in results:
                if r.file_path and Path(r.file_path).name == expected_filename:
                    return True
                if r.case_id and r.case_id == Path(expected_filename).stem:
                    return True
        except Exception:
            pass

        return False
    except Exception as e:
        logger.warning("SOP validation failed: %s", e)
        return False


def _generate_sop_filename(case_data: dict) -> str:
    """Generate a filename for a new SOP."""
    resource_type = case_data.get("resource_type", "unknown").lower()
    issue_pattern = case_data.get("issue_pattern", "issue")

    # Extract first 3 meaningful words from issue pattern
    words = []
    for word in issue_pattern.lower().split():
        word = word.strip(".,;:!?()[]{}\"'")
        if len(word) > 2 and word not in ("the", "and", "for", "was", "with", "that", "this", "from"):
            words.append(word)
        if len(words) >= 3:
            break

    slug = "-".join(words) if words else "general"
    return f"{resource_type}-{slug}.md"


def _extract_section(body: str, heading: str, stop_heading: str = "") -> str:
    """Extract text under a markdown heading (## Heading) until next heading or stop_heading."""
    import re

    pattern = rf"^##\s+{re.escape(heading)}.*?\n(.*?)(?=^##\s+|$)"
    if stop_heading:
        pattern = rf"^##\s+{re.escape(heading)}.*?\n(.*?)(?=^##\s+{re.escape(stop_heading)}|^##\s+|$)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()[:500]
    return ""
