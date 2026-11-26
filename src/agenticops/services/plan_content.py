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
from agenticops.utils.timeutils import iso_z

# The reason an execution is aborted with when the plan changed after its approval (spec §3.D.1)
CONTENT_CHANGED = "content changed after approval"
# What the deprecated `PUT /api/fix-plans/{id}` with status=rejected stores as the reason
DEPRECATED_REJECT = "(rejected via deprecated PUT status)"

HUMAN_ACTORS = ("user:", "cli:", "web:", "im:")


def rejected_by_person(plan) -> bool:
    """A PERSON said no to this plan — by any route, with or without a reason. A rejection made by code is not
    one: by an agent or the policy engine, or a plan withdrawn because its content changed after approval (that
    one is stamped with whoever started the run). The plan written after such a «no» is never approved without a
    person (pipeline_service.trigger_auto_approve; round-2 review C1)."""
    reason = (getattr(plan, "rejection_reason", None) or "").strip()
    by = getattr(plan, "rejected_by", None) or ""
    return getattr(plan, "status", None) == "rejected" and by.startswith(HUMAN_ACTORS) and reason != CONTENT_CHANGED


def rejection_is_feedback(plan) -> bool:
    """Whether a rejected plan's reason is something a PERSON wrote about the plan — what is quoted under their name
    and passed to the agent asked for the next plan (MVP-2.9.0). A person's «no» (rejected_by_person) that carries
    a sentence of theirs: not an empty reason, and not the filler the deprecated PUT writes."""
    reason = (getattr(plan, "rejection_reason", None) or "").strip()
    return rejected_by_person(plan) and bool(reason) and reason != DEPRECATED_REJECT


def previous_fix_plan(session, plan: "FixPlan"):
    """The plan before this one on the same issue — the newest OLDER fix plan, whatever became of it. None for an
    issue's first plan and for a change plan (it belongs to its change request)."""
    if plan.plan_kind != "fix" or plan.health_issue_id is None:
        return None
    return (session.query(FixPlan)
            .filter(FixPlan.health_issue_id == plan.health_issue_id, FixPlan.plan_kind == "fix", FixPlan.id < plan.id)
            .order_by(FixPlan.id.desc()).first())


def previous_plan_diff(session, plan: FixPlan) -> dict:
    """What this fix plan changed relative to the plan before it on the same issue (MVP-2.9.0 N14) — the newest
    OLDER fix plan of the issue, whatever became of it (sent back, failed, run and not accepted). A redone plan is
    a new row, and the old row keeps its content, so nothing new is stored. `previous` is None for an issue's first
    plan and for a change plan (it belongs to its change request).

    `steps` / `rollback`: change_steps.plan_diff. `same_content`: the two content hashes are equal — the plan was
    redone word for word (None when either has no hash). `same_diagnosis`: both were written from the same
    diagnosis (None when either does not say). `rejection_is_feedback`: a person wrote the reason about the plan
    (the one rule, above) — only then is it quoted under their name."""
    from agenticops.services.change_steps import plan_diff, plan_steps, rollback_steps
    from agenticops.services.verification import declared_checks
    out = {"plan_id": plan.id, "previous": None, "same_content": None, "steps": None, "rollback": None,
           "rollback_same": None, "checks": None, "risk_same": None}
    prev = previous_fix_plan(session, plan)
    if prev is None:
        return out
    out["previous"] = {
        "id": prev.id, "status": prev.status, "plan_version": prev.plan_version or 1, "risk_level": prev.risk_level,
        "created_at": iso_z(prev.created_at),
        "rejected_by": prev.rejected_by, "rejected_at": iso_z(prev.rejected_at), "rejection_reason": prev.rejection_reason,
        "rejection_is_feedback": rejection_is_feedback(prev),
        "same_diagnosis": (prev.rca_result_id == plan.rca_result_id
                           if prev.rca_result_id is not None and plan.rca_result_id is not None else None),
    }
    if prev.content_hash and plan.content_hash:
        out["same_content"] = prev.content_hash == plan.content_hash
    out["steps"] = plan_diff(plan_steps(prev.steps), plan_steps(plan.steps))
    out["rollback"] = plan_diff(rollback_steps(prev.rollback_plan), rollback_steps(plan.rollback_plan))
    # Round-2 review C-I2. The two lists above compare LINES; a rollback written as a sentence has none, and the
    # checks are not steps — yet both are part of what an approval covers. So the page is also told, whole against
    # whole: is the rollback the same (whatever its shape), are the checks, is the risk level.
    out["rollback_same"] = _canonical(prev.rollback_plan) == _canonical(plan.rollback_plan)
    pre = (plan_steps(prev.pre_checks), plan_steps(plan.pre_checks))
    post = (declared_checks(prev.post_checks), declared_checks(plan.post_checks))
    out["checks"] = {"same": _canonical(pre[0]) == _canonical(pre[1]) and _canonical(post[0]) == _canonical(post[1]),
                     "pre": [len(pre[0]), len(pre[1])], "post": [len(post[0]), len(post[1])]}
    out["risk_same"] = prev.risk_level == plan.risk_level
    return out


def _canonical(value) -> str:
    """A plan column as one comparable text: a legacy JSON string decoded (it may be encoded more than once), keys
    sorted. Prose that is no JSON stays the prose it is."""
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            break
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def content_hash(*, steps, rollback_plan, pre_checks, post_checks, account_id, risk_level) -> str:
    """sha256 of the content AS IT IS STORED. Every text / JSON column is scrubbed of secrets when it is written
    (security/db_redaction), so a plan whose step names an access key id is stored with the id masked. A hash
    stamped over the step as the agent wrote it was not the hash of the stored step — the approve route recomputed
    another one and answered «changed since it was loaded» for good (MVP-2.9.0 N15: 4 of the 80 plans waiting for
    approval on a copy of the local database). The same scrub is applied here first; it is idempotent, so stored
    content hashes as before, and content without a secret hashes exactly as it always did."""
    from agenticops.security.redaction import redact_obj
    doc = {"steps": redact_obj(steps), "rollback_plan": redact_obj(rollback_plan), "pre_checks": redact_obj(pre_checks),
           "post_checks": redact_obj(post_checks), "account_id": account_id, "risk_level": risk_level}
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


def repair_stale_hash(session, plan: FixPlan) -> bool:
    """Restamp a stored hash that is not the hash of the stored content — none at all (a plan from before 2.6.1), or
    one stamped before the database redaction rewrote the content (N15) — so that the reload a refused approval asks
    for shows a hash that CAN be approved. True = it was restamped (the caller commits)."""
    if plan.content_hash == current_hash(session, plan):
        return False
    stamp_content(session, plan)
    return True


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
