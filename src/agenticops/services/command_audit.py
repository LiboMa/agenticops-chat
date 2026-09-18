"""Command audit — tool-layer ledger of write-tier command attempts (MVP-2.6.0).

record_command() is called by run_aws_cli / run_on_host / run_kubectl / run_skill_script for
every write|unknown|blocked attempt (executed, refused, blocked, error). It reads the Run Context
for attribution and is FAIL-SOFT: any failure is logged at debug level and never changes the
tool's return value. Read-only commands are deliberately not recorded (volume).
"""

from __future__ import annotations

import logging
from typing import Optional

from agenticops.models import get_db_session

logger = logging.getLogger(__name__)

EXCERPT_LIMIT = 2000
VALID_OUTCOMES = {"executed", "refused", "blocked", "error"}


def record_command(
    *,
    tool: str,
    tier: str,
    command: str,
    outcome: str,
    account: str = "",
    region: str = "",
    target: str = "",
    exit_code: Optional[int] = None,
    output_excerpt: str = "",
    duration_ms: int = 0,
    reason: str = "",
) -> None:
    try:
        from agenticops.config import settings
        if not getattr(settings, "command_audit_enabled", True):
            return
        if outcome not in VALID_OUTCOMES:
            outcome = "error"
        from agenticops.models import CommandAudit
        from agenticops.run_context import get_run_context
        from agenticops.security import redact_secrets

        ctx = get_run_context()
        row = CommandAudit(
            actor=ctx.actor, actor_user_id=ctx.actor_user_id, on_behalf_of=ctx.on_behalf_of,
            agent_name=ctx.agent_name, tool=tool, tier=tier, account=account or "", region=region or "",
            target=(target or "")[:200], command=redact_secrets(command or "")[:10000], outcome=outcome,
            reason=(reason or None), exit_code=exit_code,
            output_excerpt=redact_secrets(output_excerpt or "")[:EXCERPT_LIMIT], duration_ms=int(duration_ms or 0),
            trace_id=ctx.trace_id, fix_plan_id=ctx.fix_plan_id, change_request_id=ctx.change_request_id,
        )
        with get_db_session() as db:
            db.add(row)
        try:
            from agenticops.audit.service import AuditService
            AuditService.maybe_prune_daily()
        except Exception:
            pass
    except Exception:
        logger.debug("command audit write failed (tool=%s outcome=%s)", tool, outcome, exc_info=True)


def approved_plan_in_context() -> Optional[int]:
    """The Run Context's plan id when that plan is approved/executing, else None."""
    try:
        from agenticops.models import FixPlan
        from agenticops.run_context import get_run_context
        pid = get_run_context().fix_plan_id
        if not pid:
            return None
        with get_db_session() as db:
            status = db.query(FixPlan.status).filter_by(id=pid).scalar()
        return pid if status in ("approved", "executing") else None
    except Exception:
        return None


def change_required_refusal(command: str, pattern: str) -> str:
    return (
        f"This command matches the high-risk pattern '{pattern}' (config/policies.yaml change_required) and "
        f"can only run inside an approved plan. Open a change request instead: in Chat type "
        f"/change <what you want changed>, or use the Web UI Plans & Changes → New change request. "
        f"Command: {command}"
    )
