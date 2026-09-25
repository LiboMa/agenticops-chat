"""Change Management agent tools (MVP-2.6.0) — thin @tool wrappers over services.change_service.

Main agent: request_change, get_change_request, list_change_requests, execute_change.
SRE agent (Mode C): get_change_request, ground_change_targets, attach_change_target,
                    evaluate_change_policy, submit_change_review.
Every wrapper turns ChangeError into readable text — an agent must never see a traceback,
and none of these tools can write a terminal state (that is change_service.on_execution_result).
"""

from __future__ import annotations

import json
import logging

from strands import tool

from agenticops.auth.actor import Actor, actor_from_run_context
from agenticops.config import settings
from agenticops.run_context import get_run_context
from agenticops.services import change_service as cs

logger = logging.getLogger(__name__)

_SOURCE_BY_KIND = {"user": "chat", "web": "chat", "cli": "cli", "im": "im", "webhook": "webhook"}


def _actor_from_context() -> Actor:
    """Acting identity for a tool call: the Run Context actor (with its permission flags), or —
    when no context was set — an agent acting on its own (Plan A ruling: a context-less tool call
    is never a human; the LLM-supplied string must not grant power)."""
    ctx = get_run_context()
    if ctx.actor == "system":
        return Actor("agent", "main")
    return actor_from_run_context(ctx)


def _plan_summary(cr_id: int) -> dict | None:
    with cs._session() as s:
        plan = cs.active_plan_for(s, cr_id)
        if plan is None:
            from agenticops.models import FixPlan
            plan = (s.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change")
                    .order_by(FixPlan.created_at.desc()).first())
        if plan is None:
            return None
        return {"id": plan.id, "status": plan.status, "risk_level": plan.risk_level, "title": plan.title,
                "steps": len(plan.steps or []), "has_rollback": bool(plan.rollback_plan),
                "post_checks": len(plan.post_checks or [])}


@tool
def request_change(title: str, description: str, account: str = "", targets: str = "",
                   change_type: str = "normal", justification: str = "") -> str:
    """Open a CHANGE REQUEST (ITSM change) for a modification the user asks for — tagging, scaling,
    configuration, network or IAM changes that are NOT fixing an incident.

    USE FOR: "add tag", "change/modify/update <resource>", "scale", "变更", "change request", "CR",
    or any write intent without a HealthIssue. NOT FOR: incident fixes (sre_agent with an issue id).
    After this, call review_change(change_request_id) so the SRE reviews it in the same turn.

    Args:
        title: Short title (<= 300 chars).
        description: What to change and why, in the user's words (include resource ids / names).
        account: Registered account name; omit for single-account deployments.
        targets: Comma-separated resource ids / ARNs / names the change touches.
        change_type: normal (default) or emergency.
        justification: Business reason, if the user gave one.

    Returns:
        Confirmation with the change reference C#N, or the reason it could not be opened.
    """
    actor = _actor_from_context()
    ctx = get_run_context()
    hints = [t.strip() for t in (targets or "").split(",") if t.strip()]
    try:
        cr = cs.create_change_request(
            source=_SOURCE_BY_KIND.get(actor.kind, "api"), actor=actor, title=title, description=description,
            account_name=account or None, targets=hints, requested_change_type=(change_type or "normal").lower(),
            justification=justification or "", chat_session_id=ctx.chat_session_id, start_review=False,
        )
    except cs.ChangeError as e:
        return f"Change request could not be opened: {e}"
    # The review is NOT started here: in chat the Main agent calls review_change (sync) right after this,
    # which would otherwise race an async review. Web/CLI intakes start their own review.
    return (f"Change request C#{cr['id']} opened ({cr['requested_change_type']}, requested by {cr['requested_by']}, "
            f"targets: {', '.join(hints) or 'none given'}). Next: call review_change({cr['id']}) to run the SRE review.")


@tool
def get_change_request(change_request_id: int) -> str:
    """Get a change request (C#N) with its current plan summary. Args: change_request_id: The C# number."""
    try:
        data = cs.get_change(change_request_id)
    except cs.ChangeError as e:
        return str(e)
    data["plan"] = _plan_summary(change_request_id)
    return json.dumps(data, default=str)[:6000]


@tool
def list_change_requests(status: str = "", limit: int = 20) -> str:
    """List change requests, newest first. Args: status: optional filter (draft, under_review, planned, approved, executing, needs_review, completed, failed, rolled_back, rejected, cancelled). limit: max rows."""
    rows = cs.list_changes(status=status or None, limit=max(1, min(int(limit or 20), 100)))
    slim = [{k: r[k] for k in ("id", "title", "status", "risk_level", "effective_change_type", "requested_by", "created_at")} for r in rows]
    return json.dumps(slim, default=str)[:6000]


@tool
def execute_change(change_request_id: int) -> str:
    """Queue execution of an APPROVED change request (C#N). Confirm with the user first.
    SAFETY: only approved changes run; the Executor works from the approved plan. Args: change_request_id: The C# number."""
    try:
        out = cs.request_execution(change_request_id, actor=_actor_from_context())
    except cs.ChangeError as e:
        return f"Cannot execute C#{change_request_id}: {e}"
    return (f"Execution #{out['execution_id']} queued for change C#{change_request_id} (plan #{out['fix_plan_id']}). "
            f"The Executor picks it up within {settings.executor_poll_interval}s.")


@tool
def ground_change_targets(change_request_id: int) -> str:
    """SRE Mode C step 2: match the request's target hints against the inventory. Returns grounded targets
    and the UNRESOLVED hints — verify those with read-only describe calls, then attach_change_target them,
    or return verdict needs_clarification. Args: change_request_id: The C# number."""
    try:
        return json.dumps(cs.ground_targets(change_request_id), default=str)[:6000]
    except cs.ChangeError as e:
        return str(e)


@tool
def attach_change_target(change_request_id: int, resource_id: str, resource_type: str, region: str = "", hint: str = "") -> str:
    """SRE Mode C: attach a target that is NOT in the inventory. The platform itself runs a read-only
    describe for it (fail-closed: not found = not attached). resource_type is one of ec2:instance,
    ec2:security-group, ec2:subnet, ec2:vpc, ec2:volume, rds:db, eks:cluster, s3:bucket, lambda:function,
    autoscaling:group, elbv2:load-balancer — or pass the resource ARN as resource_id with any type.

    Args:
        change_request_id: The C# number.
        resource_id: Resource id or ARN.
        resource_type: Type key from the list above.
        region: Region for the describe call (omit for the account default).
        hint: The requester's original wording this target resolves (e.g. a name); defaults to resource_id."""
    try:
        item = cs.attach_target(change_request_id, resource_id, resource_type, actor=_actor_from_context(), region=region, hint=hint)
    except cs.ChangeError as e:
        return f"Target not attached: {e}"
    # item is the entry AS STORED: an already inventory-grounded target keeps its evidence "inventory" (a str)
    evidence = item["evidence"]["command"] if isinstance(item["evidence"], dict) else item["evidence"]
    return (f"Target {item['resource_id']} ({item['resource_type']}) attached to C#{change_request_id} "
            f"for hint '{item['hint']}' (verified by: {evidence}).")


@tool
def evaluate_change_policy(change_request_id: int, risk_level: str, action_type: str) -> str:
    """SRE Mode C step 4: deterministic policy decision (config/policies.yaml) for this change at the
    given risk (L0-L3) and action_type (tag|scale|config|network|iam|delete|other). 'block' means you
    must return verdict rejected. Args: change_request_id, risk_level, action_type."""
    try:
        d = cs.evaluate_policy(change_request_id, risk_level.upper(), action_type.lower())
    except cs.ChangeError as e:
        return str(e)
    return json.dumps(d.to_dict())


@tool
def submit_change_review(change_request_id: int, verdict: str, risk_level: str = "", action_type: str = "",
                         reasons: str = "") -> str:
    """SRE Mode C final step: deliver your verdict. verdict is approved_for_planning (requires the change
    plan you saved with save_fix_plan(plan_kind='change'), plus risk_level and action_type),
    needs_clarification (targets could not be verified / request ambiguous) or rejected.

    Args:
        change_request_id: The C# number.
        verdict: approved_for_planning | needs_clarification | rejected.
        risk_level: L0-L3 (required for approved_for_planning).
        action_type: tag | scale | config | network | iam | delete | other (required for approved_for_planning).
        reasons: Your reasons, separated by ';' or newlines."""
    parts = [p.strip() for p in (reasons or "").replace("\n", ";").split(";") if p.strip()]
    try:
        out = cs.submit_review(change_request_id, verdict=verdict.strip().lower(),
                               risk_level=(risk_level or "").upper() or None, action_type=(action_type or "").lower() or None,
                               reasons=parts, actor=_actor_from_context())
    except cs.ChangeError as e:
        return f"Verdict not accepted: {e}"
    return (f"Verdict recorded for C#{change_request_id}: status is now '{out['status']}'"
            + (f", effective change type {out['effective_change_type']}, policy {out['policy_rule']}→{out['policy_action']}"
               if out.get("policy_rule") else "") + ".")
