import type { FixExecution, FixPlan, UiAction } from "@/api/types";
import { findAction } from "@/lib/approval";
import { latestExecution } from "@/lib/issueDetail";

export interface PlanDetailModel {
  redirect: string | null;
  actions: { approve: UiAction | null; reject: UiAction | null; execute: UiAction | null };
  runKey: "plans.run.notRun" | "plans.run.running" | "plans.run.done" | "plans.run.failed";
  /** An approved plan that will not run because of its issue — it was closed, or moved on from where the approval
   *  left it (MVP-2.9.0 N26 / N27). The page says so: leaving the button out said nothing. */
  noRun: "issue_closed" | "issue_moved" | null;
  targetLink: string | null;
  accountId: number | null;   // the account the plan runs in — part of the content hash an approval binds (final review I3)
  pollMs: number | false;     // refresh while a run can still move (final review U7)
  records: ("approved" | "withdrawn" | "rejected")[];  // the approval section's facts, in order (a withdrawal follows its approval)
}

const allowed = (plan: FixPlan, name: string) => {
  const a = findAction(plan.available_actions, name);
  return a && a.allowed ? a : null;   // a shadow-mode allowance still goes through: shown
};

/** /app/plans/:id's view model (MVP-2.7.0 S3). */
export function planDetailModel(plan: FixPlan, runs: FixExecution[] | undefined): PlanDetailModel {
  const redirect = plan.plan_kind === "change"
    ? (plan.change_request_id != null ? `/app/changes/${plan.change_request_id}` : "/app/plans?tab=changes") : null;
  const run = latestExecution(runs);
  const runKey = plan.status === "executing" || run?.status === "pending" || run?.status === "running" ? "plans.run.running"
    : run?.status === "succeeded" ? "plans.run.done"
    : run && ["failed", "aborted", "rolled_back"].includes(run.status) ? "plans.run.failed"
    : "plans.run.notRun";
  const t = plan.target;
  const run_ = findAction(plan.available_actions, "execute");
  const noRun = run_ && !run_.allowed && (run_.reason_code === "issue_closed" || run_.reason_code === "issue_moved")
    ? run_.reason_code : null;
  return {
    redirect,
    noRun,
    actions: { approve: allowed(plan, "approve"), reject: allowed(plan, "reject"), execute: allowed(plan, "execute") },
    runKey,
    targetLink: t && t.anchor_status === "anchored" && t.resource_ref != null ? `/app/resources/${t.resource_ref}` : null,
    accountId: plan.account_id ?? null,
    pollMs: plan.status === "approved" || plan.status === "executing" || run?.status === "pending" || run?.status === "running"
      ? 5000 : false,
    records: [
      ...(plan.approved_by ? ["approved" as const] : []),
      ...(plan.rejected_by ? [plan.approved_by ? "withdrawn" as const : "rejected" as const] : []),
    ],
  };
}
