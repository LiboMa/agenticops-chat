import type { FixExecution, FixPlan, UiAction } from "@/api/types";
import { findAction } from "@/lib/approval";
import { formatElapsed } from "@/lib/formatDate";
import { resultRow } from "@/lib/issueDetail";
import { runSummary } from "@/lib/runSummary";
import { stepsVm, type StepVm } from "./plan";

/** A run as the recovery briefs show it: which step failed, what a failed check was, what a person said at
 *  acceptance, or — for a run that ended well — what the code verified. Results are read the classic page's way
 *  (lib/issueDetail.resultRow, which mirrors services/verification). */

export interface RunStepVm extends StepVm {
  /** ok = reported success · bad = reported failure · skip = the run never reached it · "" = reported, no verdict */
  mark: "ok" | "bad" | "skip" | "";
  /** what the step reported (its output or its error) */
  output: string;
}

const MARK = { pass: "ok", fail: "bad", warning: "", missing: "" } as const;

export function runStepsVm(run: Pick<FixExecution, "step_results">, runPlan: FixPlan | null): RunStepVm[] {
  const results = (Array.isArray(run.step_results) ? run.step_results : []).map(resultRow);
  if (!runPlan) return results.map((r) => ({ say: r.title, cmd: null, tier: null, mark: MARK[r.outcome], output: r.output }));
  return stepsVm(runPlan).map((s, i) => {
    const r = results[i];
    return { ...s, mark: r ? MARK[r.outcome] : "skip", output: r?.output ?? "" };
  });
}

const succeeded = (run: Pick<FixExecution, "status">) => run.status === "succeeded" || run.status === "success";

/** A person asked this run to stop (N9): who, when and what they wrote. `late` = the run ended as a success all the
 *  same — its steps were already done when the stop arrived, so nothing was held back. null = nobody asked. */
export interface StopVm { by: string | null; at: string; note: string | null; late: boolean }
export function stopOf(run: Pick<FixExecution, "status" | "stop_requested_at" | "stop_requested_by" | "stop_note">): StopVm | null {
  if (!run.stop_requested_at) return null;
  return { by: run.stop_requested_by ?? null, at: run.stop_requested_at, note: run.stop_note || null, late: succeeded(run) };
}

export interface FailedVm {
  runId: number;
  /** step = the run itself failed · check = it ran, a declared check failed · rejected = a person turned the result
   *  down at acceptance · other = it failed and nothing says where */
  variant: "step" | "check" | "rejected" | "other";
  /** the first step that reported a failure (1-based); null when none did */
  failedAt: number | null;
  duration: string;
  error: string | null;
  failedChecks: { id: string | null; label: string }[];
  /** how many rollback steps ran, and how many of those failed */
  rollback: { ran: number; failed: number };
  by: string | null;
  at: string | null;
  note: string | null;
  /** a person stopped the run (N9): who, when, what they wrote; `reported` = how many step results the executor
   *  left (0 = it recorded none: which steps ran before the stop is then not known), `done` = how many of those
   *  reported success. null = nobody stopped it — it failed by itself */
  stopped: (StopVm & { done: number; reported: number }) | null;
}

export function failedVm(run: FixExecution, runPlan: FixPlan | null): FailedVm {
  const steps = (Array.isArray(run.step_results) ? run.step_results : []).map(resultRow);
  const firstBad = steps.findIndex((s) => s.outcome === "fail");
  const rollback = (Array.isArray(run.rollback_results) ? run.rollback_results : []).map(resultRow);
  const failedChecks = runSummary(run, runPlan).checks.filter((c) => c.state === "failed").map(({ id, label }) => ({ id, label }));
  const stop = stopOf(run);
  const variant = !succeeded(run) ? (firstBad >= 0 || run.error_message ? "step" : "other")
    : run.accepted_by ? "rejected" : failedChecks.length ? "check" : "other";
  return {
    runId: run.id, variant, failedAt: firstBad >= 0 ? firstBad + 1 : null, duration: formatElapsed(run.duration_ms),
    error: run.error_message, failedChecks,
    rollback: { ran: rollback.length, failed: rollback.filter((r) => r.outcome === "fail").length },
    by: run.accepted_by, at: run.accepted_at, note: run.acceptance_note,
    stopped: stop ? { ...stop, done: steps.filter((s) => s.outcome === "pass").length, reported: steps.length } : null,
  };
}

export interface ResolveVm {
  runId: number;
  /** passed = the code verified every declared check · unverified = the run closed without any verdict */
  variant: "passed" | "unverified";
  done: number;
  total: number;
  duration: string;
  version: number | null;
  hash8: string | null;
  matchesApproved: boolean | null;
  passed: { id: string | null; label: string }[];
  /** a person asked this run to stop (N9); it ended as a success all the same */
  stop: StopVm | null;
}

export function resolveVm(run: FixExecution, runPlan: FixPlan | null): ResolveVm {
  const s = runSummary(run, runPlan);
  return {
    runId: run.id, variant: run.verification_status === "passed" ? "passed" : "unverified",
    done: s.stepsDone, total: s.stepsTotal, duration: formatElapsed(run.duration_ms),
    version: s.version, hash8: s.hash8, matchesApproved: s.matchesApproved,
    passed: s.checks.filter((c) => c.state === "passed").map(({ id, label }) => ({ id, label })),
    stop: stopOf(run),
  };
}

/** Whether an approved plan (or change) may be run now, from the server's own `execute` action. */
export function executeState(actions: UiAction[] | undefined | null): { can: boolean; why: string | null; shadow: boolean } {
  const a = findAction(actions, "execute");
  if (!a) return { can: false, why: "state", shadow: false };
  return a.allowed ? { can: true, why: null, shadow: a.reason_code === "policy_shadow" } : { can: false, why: a.reason_code ?? "forbidden", shadow: false };
}
