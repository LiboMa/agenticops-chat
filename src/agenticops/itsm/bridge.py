"""ITSM bridge — mirrors pipeline lifecycle events into ITSM records.

Subscribes to agenticops.services.pipeline_events and translates the
9-state HealthIssue lifecycle into incident + change-request records:

    issue_created           → create_incident                (open)
    rca_completed           → worknote with RCA summary      (root_cause_identified)
    fix_plan_created        → create_change                  (fix_planned)
    fix_approved            → change → implement             (fix_approved)
    execution_started       → worknote                       (fix_executing)
    execution_completed     → change → review + worknote     (fix_executed)
    resolved                → close_change + resolve_incident (resolved)

Best-effort by design: ITSM mirroring never blocks or fails the pipeline.
Idempotent via the ITSMLink table (one external record per entity+system).
"""

from __future__ import annotations

import logging
from typing import Optional

from agenticops.itsm.base import ITSMAdapter, ITSMResult

logger = logging.getLogger(__name__)

_adapters: list[ITSMAdapter] = []
_started = False


# ── Adapter wiring ───────────────────────────────────────────────────


def build_adapters() -> list[ITSMAdapter]:
    """Build adapters from settings (only those with a URL configured)."""
    from agenticops.config import settings

    adapters: list[ITSMAdapter] = []
    if settings.itsm_servicenow_url:
        from agenticops.itsm.servicenow import ServiceNowAdapter

        adapters.append(
            ServiceNowAdapter(
                instance_url=settings.itsm_servicenow_url,
                username=settings.itsm_servicenow_user,
                password=settings.itsm_servicenow_password,
                dry_run=settings.itsm_dry_run,
            )
        )
    if settings.itsm_jira_url:
        from agenticops.itsm.jira import JiraAdapter

        adapters.append(
            JiraAdapter(
                base_url=settings.itsm_jira_url,
                email=settings.itsm_jira_email,
                api_token=settings.itsm_jira_api_token,
                project_key=settings.itsm_jira_project_key,
                dry_run=settings.itsm_dry_run,
            )
        )
    return adapters


def start_itsm_bridge() -> bool:
    """Subscribe the bridge to pipeline events. Returns True if active."""
    global _adapters, _started
    from agenticops.config import settings

    if not settings.itsm_enabled:
        return False
    if _started:
        return True
    _adapters = build_adapters()
    if not _adapters:
        logger.info("ITSM enabled but no backend configured (servicenow/jira URL missing)")
        return False
    from agenticops.services.pipeline_events import subscribe

    subscribe(handle_pipeline_event)
    _started = True
    logger.info(
        "ITSM bridge active: %s (dry_run=%s)",
        ", ".join(a.name for a in _adapters), settings.itsm_dry_run,
    )
    return True


def stop_itsm_bridge() -> None:
    global _adapters, _started
    from agenticops.services.pipeline_events import unsubscribe

    unsubscribe(handle_pipeline_event)
    _adapters = []
    _started = False


# ── Link persistence (idempotency) ──────────────────────────────────


def _get_link(entity_type: str, entity_id: int, system: str, record_type: str) -> Optional[str]:
    from agenticops.models import ITSMLink, get_db_session

    with get_db_session() as session:
        link = (
            session.query(ITSMLink)
            .filter_by(
                entity_type=entity_type, entity_id=entity_id,
                system=system, record_type=record_type,
            )
            .first()
        )
        return link.external_id if link else None


def _save_link(
    entity_type: str, entity_id: int, system: str, record_type: str, result: ITSMResult
) -> None:
    if not result.ok or not result.external_id:
        return
    from agenticops.models import ITSMLink, get_db_session

    with get_db_session() as session:
        exists = (
            session.query(ITSMLink)
            .filter_by(
                entity_type=entity_type, entity_id=entity_id,
                system=system, record_type=record_type,
            )
            .first()
        )
        if exists:
            return
        session.add(
            ITSMLink(
                entity_type=entity_type,
                entity_id=entity_id,
                system=system,
                record_type=record_type,
                external_id=result.external_id,
                external_ref=result.external_ref,
                url=result.url,
            )
        )


# ── Event handling ───────────────────────────────────────────────────


def handle_pipeline_event(
    health_issue_id: int, event_type: str, stage: str, status: str, detail: Optional[dict]
) -> None:
    """Pipeline-event subscriber entry point (runs on a daemon thread)."""
    detail = detail or {}
    try:
        if event_type == "issue_created":
            _on_issue_created(health_issue_id)
        elif event_type == "rca_completed":
            _on_rca_completed(health_issue_id, detail)
        elif event_type in ("fix_plan_created", "fix_plan_updated"):
            _on_fix_plan(health_issue_id, detail)
        elif event_type == "fix_approved":
            _on_fix_approved(health_issue_id, detail)
        elif event_type == "execution_started":
            _on_worknote(health_issue_id, f"AgenticOps execution started (plan #{detail.get('plan_id')}).")
        elif event_type == "execution_completed":
            _on_execution_completed(health_issue_id, status, detail)
        elif event_type in ("resolved", "issue_resolved"):
            _on_resolved(health_issue_id, detail)
    except Exception:
        logger.debug("ITSM bridge failed handling %s for issue #%d", event_type, health_issue_id, exc_info=True)


def _load_issue(health_issue_id: int):
    from agenticops.models import HealthIssue, get_db_session
    from types import SimpleNamespace

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
        if not issue:
            return None
        return SimpleNamespace(
            id=issue.id, title=issue.title, description=issue.description,
            severity=issue.severity, resource_id=issue.resource_id,
            trace_id=issue.trace_id, status=issue.status,
        )


def _on_issue_created(health_issue_id: int) -> None:
    issue = _load_issue(health_issue_id)
    if not issue:
        return
    for adapter in _adapters:
        if _get_link("health_issue", issue.id, adapter.name, "incident"):
            continue
        result = adapter.create_incident(
            title=f"[AgenticOps] {issue.title}",
            description=f"{issue.description}\n\nResource: {issue.resource_id}\nTrace: {issue.trace_id}",
            severity=issue.severity,
            correlation_id=f"AIOPS-HI-{issue.id}",
            resource_id=issue.resource_id,
        )
        _save_link("health_issue", issue.id, adapter.name, "incident", result)
        if result.ok:
            logger.info("ITSM[%s]: incident %s for issue #%d", adapter.name, result.external_ref, issue.id)
        else:
            logger.warning("ITSM[%s]: create_incident failed: %s", adapter.name, result.error)


def _on_rca_completed(health_issue_id: int, detail: dict) -> None:
    summary = detail.get("root_cause") or detail.get("summary") or "RCA completed."
    confidence = detail.get("confidence")
    note = f"AgenticOps RCA:\n{summary}"
    if confidence is not None:
        note += f"\nConfidence: {confidence}"
    for adapter in _adapters:
        ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        if ext:
            adapter.update_incident_state(ext, "in_progress")
            adapter.append_worknote(ext, note)


def _on_fix_plan(health_issue_id: int, detail: dict) -> None:
    plan_id = detail.get("plan_id")
    if not plan_id:
        return
    from agenticops.models import FixPlan, get_db_session

    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            return
        steps = "\n".join(
            f"{i + 1}. {s.get('description', s) if isinstance(s, dict) else s}"
            for i, s in enumerate(plan.steps or [])
        )
        rollback = str(plan.rollback_plan or {})
        title = plan.title
        summary = plan.summary
        risk = plan.risk_level

    # change type from policy (decision recorded by pipeline) or risk default
    change_type = (detail.get("policy_decision") or {}).get("itsm_change_type") or (
        "standard" if risk in ("L0", "L1") else "normal"
    )
    for adapter in _adapters:
        if _get_link("fix_plan", plan_id, adapter.name, "change"):
            continue
        incident_ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        result = adapter.create_change(
            incident_external_id=incident_ext,
            change_type=change_type,
            title=f"[AgenticOps] {title}",
            description=summary,
            implementation_plan=steps,
            backout_plan=rollback,
            risk_level=risk,
            correlation_id=f"AIOPS-FP-{plan_id}",
        )
        _save_link("fix_plan", plan_id, adapter.name, "change", result)
        if result.ok:
            logger.info("ITSM[%s]: change %s for plan #%d (%s)", adapter.name, result.external_ref, plan_id, change_type)


def _on_fix_approved(health_issue_id: int, detail: dict) -> None:
    plan_id = detail.get("plan_id")
    if not plan_id:
        return
    approved_by = detail.get("approved_by", "unknown")
    rule = (detail.get("policy_decision") or {}).get("rule", "")
    note = f"Fix plan #{plan_id} approved by {approved_by}."
    if rule:
        note += f" Policy rule: {rule}."
    for adapter in _adapters:
        change_ext = _get_link("fix_plan", plan_id, adapter.name, "change")
        if change_ext:
            adapter.update_change_state(change_ext, "implement")
            if hasattr(adapter, "append_change_worknote"):
                adapter.append_change_worknote(change_ext, note)
        incident_ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        if incident_ext:
            adapter.append_worknote(incident_ext, note)


def _on_worknote(health_issue_id: int, note: str) -> None:
    for adapter in _adapters:
        ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        if ext:
            adapter.append_worknote(ext, note)


def _on_execution_completed(health_issue_id: int, status: str, detail: dict) -> None:
    plan_id = detail.get("plan_id")
    note = f"Execution of plan #{plan_id} finished: {status}."
    for adapter in _adapters:
        change_ext = _get_link("fix_plan", plan_id, adapter.name, "change") if plan_id else None
        if change_ext:
            adapter.update_change_state(change_ext, "review")
            if hasattr(adapter, "append_change_worknote"):
                adapter.append_change_worknote(change_ext, note)
        incident_ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        if incident_ext:
            adapter.append_worknote(incident_ext, note)


def _on_resolved(health_issue_id: int, detail: dict) -> None:
    from agenticops.models import FixPlan, get_db_session

    plan_ids: list[int] = []
    try:
        with get_db_session() as session:
            plan_ids = [
                p.id for p in session.query(FixPlan).filter_by(health_issue_id=health_issue_id).all()
            ]
    except Exception:
        pass
    close_notes = detail.get("summary") or "Auto-remediated by AgenticOps; post-fix verification passed."
    for adapter in _adapters:
        for plan_id in plan_ids:
            change_ext = _get_link("fix_plan", plan_id, adapter.name, "change")
            if change_ext:
                adapter.close_change(change_ext, success=True, notes=close_notes)
        incident_ext = _get_link("health_issue", health_issue_id, adapter.name, "incident")
        if incident_ext:
            adapter.resolve_incident(incident_ext, close_notes)
            logger.info("ITSM[%s]: resolved incident for issue #%d", adapter.name, health_issue_id)
