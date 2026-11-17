import type { FixExecution, FixPlan } from "@/api/types";
import { formatElapsed } from "@/lib/formatDate";
import { runSummary } from "@/lib/runSummary";

/** Acceptance: a run that succeeded but that the code could not call «passed» — a declared check has no result, more
 *  than one, or a warning — waits for a person's verdict. The rules are the classic page's (lib/runSummary). */

/** The run a person is asked to accept: the issue's newest run (the list is newest first), and only while it is
 *  pending acceptance — the server refuses an older one (409). */
export function runToAccept(runs: FixExecution[] | undefined): FixExecution | null {
  const latest = runs?.[0];
  return latest && latest.verification_status === "pending_acceptance" ? latest : null;
}

export interface AcceptVm {
  runId: number;
  stepsDone: number;
  stepsTotal: number;
  duration: string;
  /** the plan the run executed — its own, not the issue's current one; null when it could not be loaded */
  planVersion: number | null;
  hash8: string | null;
  /** the plan's content still is what was approved; null = unknown (never read as «changed») */
  matchesApproved: boolean | null;
  /** the server's sentence on why this run needs a person */
  reason: string | null;
  passed: { id: string | null; label: string }[];
  toVerify: { id: string | null; label: string; state: "pending" | "warning" }[];
  failed: { id: string | null; label: string }[];
}

export function acceptVm(run: FixExecution, runPlan: FixPlan | null): AcceptVm {
  const s = runSummary(run, runPlan);
  const pick = (state: string) => s.checks.filter((c) => c.state === state).map(({ id, label }) => ({ id, label }));
  return {
    runId: run.id,
    stepsDone: s.stepsDone,
    stepsTotal: s.stepsTotal,
    duration: formatElapsed(run.duration_ms),
    planVersion: s.version,
    hash8: s.hash8,
    matchesApproved: s.matchesApproved,
    reason: run.verification_reason,
    passed: pick("passed"),
    toVerify: s.checks.filter((c) => c.state === "pending" || c.state === "warning")
      .map(({ id, label, state }) => ({ id, label, state: state as "pending" | "warning" })),
    failed: pick("failed"),
  };
}
