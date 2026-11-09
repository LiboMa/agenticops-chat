import type { FixExecution, FixPlan } from "@/api/types";
import { resultSummary } from "@/lib/issueDetail";
import { planCounts, shortHash } from "@/lib/plans";
import { postCheckRows } from "@/lib/postChecks";

export type CheckState = "passed" | "failed" | "warning" | "pending";

export interface RunSummary {
  stepsDone: number;
  stepsTotal: number;
  /** the run's own plan — never the issue's current plan when the run belongs to an older one */
  planId: number | null;
  version: number | null;
  hash8: string | null;
  /** the plan's content still matches what was approved; null when the plan is unknown */
  matchesApproved: boolean | null;
  /** one per declared post-check, from the server's binding: a check with no result is pending («待核对») */
  checks: { id: string | null; label: string; state: CheckState }[];
  warnings: string[];
}

const STATE: Record<string, CheckState> = { pass: "passed", fail: "failed", warning: "warning" };

/** The first screen's latest-run block (MVP-2.8.0 S2): steps done against the run's own plan, the approval binding,
 *  each declared check's state and the warnings. `runPlan` = the plan `run.fix_plan_id` names (null if unknown). */
export function runSummary(run: FixExecution, runPlan: FixPlan | null): RunSummary {
  const steps = resultSummary(run.step_results ?? []);
  const { rows } = postCheckRows(run);
  const checks = rows.map((r) => ({
    id: r.label.startsWith("pc-") ? r.label : null,
    label: r.title || r.label,
    state: r.problem ? "pending" as CheckState : STATE[r.outcome ?? ""] ?? "pending",
  }));
  return {
    stepsDone: steps.pass,
    stepsTotal: runPlan ? planCounts(runPlan).steps : (run.step_results ?? []).length,
    planId: runPlan?.id ?? null,
    version: runPlan ? runPlan.plan_version || 1 : null,
    hash8: runPlan?.content_hash ? shortHash(runPlan.content_hash) : null,
    matchesApproved: runPlan ? !!runPlan.approved_hash && runPlan.approved_hash === runPlan.content_hash : null,
    checks,
    warnings: checks.filter((c) => c.state === "warning").map((c) => c.label),
  };
}

const ORDER: Record<CheckState, number> = { failed: 0, pending: 1, warning: 2, passed: 3 };

/** The checks a person must look at come first on the first screen (failed, to check, warnings), the passed ones
 *  after — a long plan's passed checks must not push the one «待核对» below the fold. Stable inside each state. */
export function checksNeedingYouFirst<T extends { state: CheckState }>(checks: T[]): T[] {
  return checks.map((c, i) => [c, i] as const).sort((a, b) => ORDER[a[0].state] - ORDER[b[0].state] || a[1] - b[1]).map(([c]) => c);
}
