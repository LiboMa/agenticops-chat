"""Post-RCA quality pipeline — evidence verification, critic review, confidence gate.

Runs after every rca_agent invocation (all entry points funnel through
rca_agent), replacing the auto-SRE/notify side effects that used to live
inside save_rca_result:

    1. evidence gate   — each cited evidence.ref must appear in the agent's
                         actual tool trace this run (fail-closed penalty)
    2. critic review   — a cheap-tier adversarial pass tries to refute the
                         root cause (verdict persisted)
    3. confidence gate — only confident, un-refuted RCA triggers auto-SRE;
                         otherwise the issue is flagged needs_review

Every step is fail-soft: an internal error never blocks the pipeline, it
just skips that check (logged).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from agenticops.config import settings

logger = logging.getLogger(__name__)

EVIDENCE_PENALTY = 0.6   # multiplier when cited evidence is not grounded
CRITIC_PENALTY = 0.5     # multiplier when the critic refutes the root cause


def run_post_rca_pipeline(issue_id: int, messages: list, started_at: datetime) -> None:
    """Verify, critique, and gate the RCAResult produced in this run."""
    from agenticops.models import RCAResult, get_db_session
    from agenticops.services.pipeline_events import log_event

    with get_db_session() as session:
        rca = (
            session.query(RCAResult)
            .filter(RCAResult.health_issue_id == issue_id,
                    RCAResult.created_at >= started_at.replace(tzinfo=None))
            .order_by(RCAResult.created_at.desc())
            .first()
        )
        if rca is None:
            # Also accept a result with tz-aware storage or minor clock skew
            rca = (
                session.query(RCAResult)
                .filter(RCAResult.health_issue_id == issue_id)
                .order_by(RCAResult.created_at.desc())
                .first()
            )
            if rca is None or (rca.created_at and rca.created_at.replace(tzinfo=timezone.utc) < started_at):
                log_event(issue_id, "rca_completed", "rca", "failed",
                          detail={"reason": "no_result"})
                _flag_needs_review(issue_id, "RCA run produced no result")
                logger.warning("post-RCA: no RCAResult produced for issue #%d", issue_id)
                return
        rca_id = rca.id
        confidence = float(rca.confidence or 0.0)
        root_cause = rca.root_cause or ""
        evidence_items = rca.evidence if isinstance(rca.evidence, list) else []

    # ── 1. Evidence gate (deterministic, fail-closed) ────────────────
    verified = None
    unmatched: list[str] = []
    try:
        if evidence_items:
            trace_text = _tool_trace_text(messages)
            unmatched = [
                str(item.get("ref", ""))
                for item in evidence_items
                if isinstance(item, dict) and item.get("ref")
                and not _ref_in_trace(str(item["ref"]), trace_text)
            ]
            verified = not unmatched
            if not verified:
                confidence = round(confidence * EVIDENCE_PENALTY, 3)
                logger.info("post-RCA: evidence NOT grounded for issue #%d (%s) — confidence ×%.1f",
                            issue_id, unmatched[:3], EVIDENCE_PENALTY)
    except Exception:
        logger.debug("evidence verification failed (skipped)", exc_info=True)

    # ── 2. Critic review (cheap tier, adversarial) ───────────────────
    critic_verdict = None
    critic_notes = None
    if settings.rca_critic_enabled:
        try:
            critic_verdict, critic_notes = _run_critic(issue_id, root_cause, evidence_items, verified)
            if critic_verdict == "refuted":
                confidence = round(confidence * CRITIC_PENALTY, 3)
        except Exception:
            logger.debug("critic review failed (skipped)", exc_info=True)

    # ── Persist quality fields ────────────────────────────────────────
    with get_db_session() as session:
        rca = session.query(RCAResult).filter_by(id=rca_id).first()
        if rca:
            rca.evidence_verified = verified
            rca.confidence = confidence
            if critic_verdict:
                rca.critic_verdict = critic_verdict
                rca.critic_notes = critic_notes
        trace_id = None
        issue = rca.health_issue if rca else None
        if issue is not None:
            trace_id = issue.trace_id

    if verified is not None:
        log_event(issue_id, "rca_evidence_check", "rca",
                  "completed" if verified else "failed",
                  detail={"rca_id": rca_id, "verified": verified,
                          "unmatched_refs": unmatched[:5]})
    if critic_verdict:
        log_event(issue_id, "rca_critic", "rca",
                  "completed" if critic_verdict != "refuted" else "failed",
                  detail={"rca_id": rca_id, "verdict": critic_verdict,
                          "notes": (critic_notes or "")[:200]})

    # ── 3. Confidence gate → auto-SRE or needs_review ────────────────
    gate_pass = (confidence >= settings.rca_min_confidence_for_autofix
                 and critic_verdict != "refuted")
    if gate_pass:
        try:
            from agenticops.services.pipeline_service import trigger_auto_sre

            trigger_auto_sre(issue_id, trace_id=trace_id)
        except Exception:
            logger.warning("post-RCA: auto-SRE trigger failed for #%d", issue_id, exc_info=True)
        try:
            from agenticops.services.notification_service import notify_rca_completed, notify_im_origin

            notify_rca_completed(issue_id, root_cause, confidence)
            notify_im_origin(
                issue_id, "rca_completed",
                f"RCA completed for Issue #{issue_id}: {root_cause[:200]}. Confidence: {confidence:.0%}",
            )
        except Exception:
            logger.debug("post-RCA notification failed", exc_info=True)
    else:
        reason = ("critic refuted the root cause" if critic_verdict == "refuted"
                  else f"confidence {confidence:.2f} < {settings.rca_min_confidence_for_autofix}")
        _flag_needs_review(issue_id, reason)
        log_event(issue_id, "rca_needs_review", "rca", "completed",
                  detail={"rca_id": rca_id, "confidence": confidence,
                          "critic_verdict": critic_verdict, "reason": reason})
        try:
            from agenticops.services.notification_service import notify_event

            notify_event(
                "rca_needs_review",
                f"RCA needs review — Issue #{issue_id}",
                f"Root cause: {root_cause[:300]}\nReason: {reason}\nAuto-fix NOT triggered.",
                severity="medium",
            )
        except Exception:
            logger.debug("needs_review notification failed", exc_info=True)
        logger.info("post-RCA: issue #%d flagged needs_review (%s)", issue_id, reason)


# ── helpers ───────────────────────────────────────────────────────────


def _tool_trace_text(messages: list) -> str:
    """Flatten every toolUse input and toolResult content in the run to text."""
    chunks: list[str] = []
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if "toolUse" in block:
                try:
                    chunks.append(json.dumps(block["toolUse"].get("input", {}), default=str))
                except Exception:
                    pass
            if "toolResult" in block:
                for part in block["toolResult"].get("content", []) or []:
                    if isinstance(part, dict):
                        text = part.get("text") or ""
                        if text:
                            chunks.append(str(text))
                        elif "json" in part:
                            try:
                                chunks.append(json.dumps(part["json"], default=str))
                            except Exception:
                                pass
    return "\n".join(chunks).lower()


def _ref_in_trace(ref: str, trace_text: str) -> bool:
    """Grounding check: the ref (or all its significant tokens) appears in the trace."""
    needle = ref.strip().lower()
    if not needle:
        return True
    if needle in trace_text:
        return True
    # Token fallback: every alphanumeric token ≥4 chars must appear —
    # tolerates formatting differences without accepting fabrications.
    tokens = [t for t in re.findall(r"[a-z0-9][a-z0-9._:/-]{3,}", needle)]
    if not tokens:
        return True
    return all(t in trace_text for t in tokens)


def _run_critic(issue_id: int, root_cause: str, evidence_items: list,
                evidence_verified) -> tuple:
    """One cheap-tier adversarial pass. Returns (verdict, notes)."""
    from agenticops.services.signal_gate import _call_bedrock, _parse_verdict

    model_id = settings.rca_critic_model_id or settings.bedrock_model_id_cheap
    issue_summary = ""
    try:
        from agenticops.models import HealthIssue, get_db_session

        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=issue_id).first()
            if issue:
                issue_summary = f"[{issue.severity}] {issue.title} — {issue.description[:300]}"
    except Exception:
        pass

    prompt = (
        "You are an adversarial reviewer of a root-cause analysis. Try to REFUTE it:\n"
        "does the evidence actually support the conclusion? Is there an obvious\n"
        "alternative explanation it ignored?\n"
        "Respond with ONLY this JSON:\n"
        '{"verdict": "supported" | "weak" | "refuted", "notes": "<short reasoning>"}\n'
        "- supported: evidence clearly backs the root cause\n"
        "- weak: plausible but under-evidenced or alternatives not excluded\n"
        "- refuted: evidence contradicts it or a better explanation exists\n\n"
        f"ISSUE: {issue_summary}\n"
        f"ROOT CAUSE CLAIMED: {root_cause[:800]}\n"
        f"EVIDENCE CITED ({'grounded' if evidence_verified else 'NOT grounded in tool trace' if evidence_verified is False else 'none provided'}): "
        f"{json.dumps(evidence_items[:8], default=str)}"
    )
    text, _usage = _call_bedrock(prompt, model_id)
    verdict = _parse_verdict(text) or {}
    v = str(verdict.get("verdict", "")).lower()
    if v not in ("supported", "weak", "refuted"):
        return None, None
    return v, str(verdict.get("notes", ""))[:1000]


def _flag_needs_review(issue_id: int, reason: str) -> None:
    from agenticops.services.rca_service import _flag_needs_review as _impl

    _impl(issue_id, reason)
