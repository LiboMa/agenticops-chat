"""A plan's content identity (MVP-2.6.1 spec §3.D.1): its version, its content hash, and the hash its approval was for.

content_hash is sha256 over the canonical JSON (sorted keys, compact separators) of what an execution would run:
steps, rollback, pre/post checks, the target account and the risk level. Title, summary and impact are prose and
are left out. Every content write restamps it; a changed hash is a new version. Approval records the hash and
version it approved, and get_approved_fix_plan refuses a plan whose recomputed hash no longer matches.
"""

import hashlib
import json
from typing import Optional

from agenticops.models import FIXPLAN_TERMINAL_STATUSES, ChangeRequest, FixPlan, HealthIssue

# The reason an execution is aborted with when the plan changed after its approval (spec §3.D.1)
CONTENT_CHANGED = "content changed after approval"


def content_hash(*, steps, rollback_plan, pre_checks, post_checks, account_id, risk_level) -> str:
    doc = {"steps": steps, "rollback_plan": rollback_plan, "pre_checks": pre_checks, "post_checks": post_checks,
           "account_id": account_id, "risk_level": risk_level}
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_account_id(session, plan: FixPlan) -> Optional[int]:
    """The account the plan runs against: its change request's, else its issue's."""
    if plan.plan_kind == "change":
        cr = session.get(ChangeRequest, plan.change_request_id) if plan.change_request_id else None
        return cr.account_id if cr else None
    issue = session.get(HealthIssue, plan.health_issue_id) if plan.health_issue_id else None
    return issue.account_id if issue else None


def current_hash(session, plan: FixPlan) -> str:
    """The hash of the plan's content as it is now (recomputed, never read from the column)."""
    return content_hash(steps=plan.steps, rollback_plan=plan.rollback_plan, pre_checks=plan.pre_checks,
                        post_checks=plan.post_checks, account_id=plan_account_id(session, plan),
                        risk_level=plan.risk_level)


def stamp_content(session, plan: FixPlan) -> None:
    """Restamp content_hash after a content write. A new plan is v1; a changed hash is the next version."""
    new = current_hash(session, plan)
    if plan.content_hash is None:
        plan.plan_version = plan.plan_version or 1
    elif new != plan.content_hash:
        plan.plan_version = (plan.plan_version or 1) + 1
    plan.content_hash = new


def restamp_issue_plans(session, issue_id: int) -> None:
    """An issue's account is part of its plans' content: restamp its live plans after the account moves."""
    for plan in session.query(FixPlan).filter(FixPlan.health_issue_id == issue_id,
                                              FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES)):
        stamp_content(session, plan)


def stamp_approval(session, plan: FixPlan) -> None:
    """Record what an approval approved — call right after the plan moves to approved."""
    stamp_content(session, plan)
    plan.approved_hash, plan.approved_version = plan.content_hash, plan.plan_version


def approval_conflict(session, plan: FixPlan, seen_hash: str) -> Optional[str]:
    """Why an approval of `seen_hash` must be refused (409): the plan is no longer that content. None = it is."""
    now = current_hash(session, plan)
    if seen_hash == now:
        return None
    return (f"{plan_label(plan)} changed since it was loaded (content {now[:12]}, not {(seen_hash or '')[:12]}); "
            f"reload it and review it again.")


def approval_drift(session, plan: FixPlan) -> Optional[str]:
    """Why an approved plan must not run: its content is no longer what was approved. None = it is."""
    if plan.approved_hash and plan.approved_hash == current_hash(session, plan):
        return None
    return (f"{plan_label(plan)}: {CONTENT_CHANGED} "
            f"(approved v{plan.approved_version or '?'}, now v{plan.plan_version or '?'})")


def plan_label(plan: FixPlan) -> str:
    """How a plan is named to people: "I#12 fix plan v2" / "C#3 implementation plan v1"."""
    if plan.plan_kind == "change":
        return f"C#{plan.change_request_id} implementation plan v{plan.plan_version or 1}"
    return f"I#{plan.health_issue_id} fix plan v{plan.plan_version or 1}"
