"""Post-resolution service — triggers RAG pipeline and case distillation on issue resolution.

When a HealthIssue transitions to "resolved", this service runs in a background
thread to:
1. Run the RAG pipeline (SOP generation/upgrade)
2. Distill a case study from the resolved issue
3. Log results for observability

Non-blocking: all work happens in a daemon thread so the caller returns immediately.
"""

import logging
import threading
from datetime import datetime, timezone

from agenticops.config import settings

logger = logging.getLogger(__name__)


def trigger_post_resolution(health_issue_id: int) -> None:
    """Fire-and-forget: spawn a daemon thread to run post-resolution pipeline.

    Called when a HealthIssue transitions to "resolved" status.
    Safe to call from any context (API handler, metadata tool, etc.).
    """
    if not settings.rag_pipeline_enabled:
        logger.info("RAG pipeline disabled — skipping post-resolution for issue #%d", health_issue_id)
        return

    thread = threading.Thread(
        target=_run_post_resolution,
        args=(health_issue_id,),
        daemon=True,
        name=f"post-resolution-{health_issue_id}",
    )
    thread.start()
    logger.info("Post-resolution pipeline spawned for HealthIssue #%d", health_issue_id)


def _run_post_resolution(health_issue_id: int) -> None:
    """Run RAG pipeline + case distillation for a resolved issue."""
    from agenticops.models import HealthIssue, get_db_session

    # Verify issue is actually resolved
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue or issue.status != "resolved":
            logger.warning(
                "Post-resolution skipped: issue #%d status=%s",
                health_issue_id,
                issue.status if issue else "not found",
            )
            return

    from agenticops.services.pipeline_events import log_event

    log_event(health_issue_id, "resolved", "resolution",
              detail={"auto_resolved": True})

    # Step 1: RAG pipeline (SOP generation/upgrade)
    rag_result = None
    try:
        from agenticops.pipeline.rag_pipeline import run_rag_pipeline

        logger.info("Running RAG pipeline for HealthIssue #%d", health_issue_id)
        rag_result = run_rag_pipeline(health_issue_id)
        logger.info(
            "RAG pipeline result for #%d: action=%s, success=%s, sop=%s",
            health_issue_id,
            rag_result.action,
            rag_result.success,
            rag_result.sop_filename or "none",
        )
    except Exception:
        logger.exception("RAG pipeline failed for HealthIssue #%d", health_issue_id)

    # Step 2: Case distillation
    case_id = None
    try:
        from agenticops.tools.kb_tools import distill_case_study

        logger.info("Distilling case study for HealthIssue #%d", health_issue_id)
        distill_result = distill_case_study(health_issue_id)
        logger.info("Case distillation for #%d: %s", health_issue_id, distill_result[:200])
    except Exception:
        logger.exception("Case distillation failed for HealthIssue #%d", health_issue_id)

    # Log post-resolution pipeline event
    log_event(health_issue_id, "post_resolution", "resolution",
              "completed" if rag_result and rag_result.success else "failed",
              detail={
                  "sop": rag_result.sop_filename if rag_result else None,
                  "rag_action": rag_result.action if rag_result else None,
              })

    # Step 3: Skill gap analysis (self-improving skills)
    if settings.skills_auto_improve_enabled and settings.skills_post_resolution_review:
        try:
            from agenticops.services.skill_improvement_service import (
                analyze_skill_gaps,
                trigger_skill_improvement,
                run_skill_improvement,
            )

            gaps = analyze_skill_gaps(health_issue_id)
            for gap in gaps:
                if gap.get("confidence", 0) >= 0.4:
                    result = trigger_skill_improvement(
                        skill_name=gap["skill_name"],
                        gap_description=gap["gap_description"],
                        trigger="post_resolution",
                        source_issue_id=health_issue_id,
                    )
                    if "error" not in result:
                        run_skill_improvement(
                            record_id=result["record_id"],
                            skill_name=gap["skill_name"],
                            gap_description=gap["gap_description"],
                        )
                    logger.info(
                        "Skill improvement triggered for '%s' from issue #%d (confidence=%.1f)",
                        gap["skill_name"], health_issue_id, gap["confidence"],
                    )
        except Exception:
            logger.exception("Skill gap analysis failed for HealthIssue #%d", health_issue_id)

    # Step 4: Record pipeline run in DB (for observability)
    try:
        _record_pipeline_run(health_issue_id, rag_result)
    except Exception:
        logger.exception("Failed to record pipeline run for #%d", health_issue_id)


def _record_pipeline_run(health_issue_id: int, rag_result) -> None:
    """Record pipeline execution metadata in the HealthIssue notes."""
    from agenticops.models import HealthIssue, get_db_session

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return

        # Store pipeline results as JSON in description addendum
        pipeline_note = f"\n\n[Auto] Post-resolution pipeline ran at {datetime.now(timezone.utc).isoformat()}"
        if rag_result:
            pipeline_note += f" | RAG: {rag_result.action}"
            if rag_result.sop_filename:
                pipeline_note += f" → {rag_result.sop_filename}"

        if issue.description:
            issue.description += pipeline_note
        else:
            issue.description = pipeline_note.strip()

        session.commit()
