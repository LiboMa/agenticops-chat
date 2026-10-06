import type { FixExecution, FixPlan, UiAction } from "@/api/types";
import { findAction } from "@/lib/approval";
import { latestExecution } from "@/lib/issueDetail";

export interface PlanDetailModel {
  redirect: string | null;
  actions: { approve: UiAction | null; reject: UiAction | null; execute: UiAction | null };
  runKey: "plans.run.notRun" | "plans.run.running" | "plans.run.done" | "plans.run.failed";
  targetLink: string | null;
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
  return {
    redirect,
    actions: { approve: allowed(plan, "approve"), reject: allowed(plan, "reject"), execute: allowed(plan, "execute") },
    runKey,
    targetLink: t && t.anchor_status === "anchored" && t.resource_ref != null ? `/app/resources/${t.resource_ref}` : null,
  };
}
