import type { FixExecution, FixPlan, IssueStatus, RCAResult } from "@/api/types";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export type IssuePhaseId = "diagnose" | "plan" | "run" | "accept";
export type PhaseState = "done" | "current" | "future" | "failed";
export interface PhaseView<I extends string = string> { id: I; state: PhaseState }
export type WaitingFor = "rca_agent" | "you" | "sre_agent" | "approver" | "executor" | "requester" | "acceptor" | null;
export type IssuePrimary = "reviewRca" | "rerunRca" | "generatePlan" | "approveAndRun" | "retryExecution"
  | "acceptResult" | "markResolved" | null;
export type IssueSub = "running" | "needsReview" | "rcaRejected" | "reviewOrPlan" | "toGenerate" | "needsNewPlan" | "planRejected"
  | "awaitingApproval" | "notQueued" | "executing" | "awaitingAcceptance" | "passed" | "unverified" | "resolved" | "dismissed"
  | "loadingRuns" | "runsUnavailable" // detail page only (issueDetailModel): the runs are not known yet / failed to load
  | "rcaUnavailable"                   // detail page only: the RCA failed to load, so where the issue stands is not known
  | "checkingRun" | "runStateUnavailable" // detail page only: approved, no run row — whether its auto-run started is
                                          // not known yet (timeline / plans loading or older than the approval) / failed
  | "unknown"; // a status this page does not know (a newer backend)

export interface IssuePhaseInput {
  status: IssueStatus;
  rca?: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict" | "human_verdict"> | null;
  threshold?: number | null;
  plan?: Pick<FixPlan, "status"> | null;
  latestRun?: Pick<FixExecution, "status" | "verification_status"> | null;
  autoRunInFlight?: boolean; // the approval's auto-run is under way: it has no run row until it ends (final review C1)
}

export interface IssuePhaseResult {
  current: IssuePhaseId | null;
  sub: IssueSub;
  waitingFor: WaitingFor;
  primary: IssuePrimary;
  phases: PhaseView<IssuePhaseId>[];
}

export const ISSUE_PHASES: readonly IssuePhaseId[] = ["diagnose", "plan", "run", "accept"];
const APPROVABLE = new Set(["draft", "pending_approval"]);
const IN_FLIGHT = new Set(["pending", "running"]);

function line(current: IssuePhaseId, failed: IssuePhaseId[] = []): PhaseView<IssuePhaseId>[] {
  const at = ISSUE_PHASES.indexOf(current);
  return ISSUE_PHASES.map((id, i) => ({
    id, state: failed.includes(id) ? "failed" : i < at ? "done" : i === at ? "current" : "future",
  }));
}

function result(current: IssuePhaseId, sub: IssueSub, waitingFor: WaitingFor, primary: IssuePrimary,
                failed: IssuePhaseId[] = []): IssuePhaseResult {
  return { current, sub, waitingFor, primary, phases: line(current, failed) };
}

/** Spec §4: where an issue is, why, who moves it next and the page's one primary button. `rca: undefined`
 *  is list mode (R2): the list has no RCA, so root_cause_identified cannot tell review from plan. Likewise
 *  `latestRun: undefined` means the runs are not known, `null` that there is none. */
export function issuePhases(i: IssuePhaseInput): IssuePhaseResult {
  const run = i.latestRun ?? null;
  switch (i.status) {
    case "open":
    case "investigating":
    case "acknowledged":
      return result("diagnose", "running", "rca_agent", null);
    case "root_cause_identified": {
      if (run && (run.verification_status === "failed" || run.status === "failed" || run.status === "aborted"
                  || run.status === "rolled_back")) {
        return result("plan", "needsNewPlan", "you", "generatePlan", ["run"]);
      }
      if (i.rca === undefined) return result("diagnose", "reviewOrPlan", "you", null);
      if (i.rca === null) return result("diagnose", "needsReview", "you", "rerunRca");
      if (i.rca.human_verdict === "incorrect") return result("diagnose", "rcaRejected", "you", "rerunRca");
      if (i.rca.human_verdict === "correct") return result("plan", "toGenerate", "you", "generatePlan");
      const gate = confidenceBreakdown(i.rca, i.threshold).gatePassed;
      if (gate === null) return result("diagnose", "reviewOrPlan", "you", null);
      return gate ? result("plan", "toGenerate", "sre_agent", "generatePlan")
                  : result("diagnose", "needsReview", "you", "reviewRca");
    }
    case "fix_planned":
      // the plan was rejected: nobody can approve it — a new plan is generated (the backend allows it: no locked plan)
      if (i.plan?.status === "rejected") return result("plan", "planRejected", "you", "generatePlan");
      return result("run", "awaitingApproval", "approver", i.plan && APPROVABLE.has(i.plan.status) ? "approveAndRun" : null);
    case "fix_approved":
      // latestRun undefined = the runs are not known (list mode): approving queues the run, so never claim "not queued".
      // An approval's auto-run writes no row until it ends: the timeline's signal says it is running.
      if (i.latestRun === undefined || (run && IN_FLIGHT.has(run.status)) || i.autoRunInFlight) {
        return result("run", "executing", "executor", null);
      }
      return result("run", "notQueued", "you", "retryExecution");
    case "fix_executing":
      return result("run", "executing", "executor", null);
    case "fix_executed":
      if (run?.verification_status === "pending_acceptance") return result("accept", "awaitingAcceptance", "acceptor", "acceptResult");
      if (run?.verification_status === "passed") return result("accept", "passed", "you", "markResolved");
      return result("accept", "unverified", "you", run ? "markResolved" : null);
    case "resolved":
    case "dismissed":
      return reachedOnly(i, i.status);
    default: // degrade, never throw: no button, nobody waited on
      return reachedOnly(i, "unknown");
  }
}

/** No current phase: the phases there is data for read done, the rest future. */
function reachedOnly(i: IssuePhaseInput, sub: IssueSub): IssuePhaseResult {
  const run = i.latestRun ?? null;
  const reached: Record<IssuePhaseId, boolean> = {
    diagnose: !!i.rca, plan: !!i.plan, run: !!run, accept: run?.verification_status === "passed" || (i.status === "resolved" && !!run),
  };
  return { current: null, sub, waitingFor: null, primary: null,
           phases: ISSUE_PHASES.map((id) => ({ id, state: reached[id] ? "done" : "future" })) };
}

const TERMINAL_PLAN = new Set(["executed", "failed", "rejected"]);

/** The plan the page shows and approves: the newest not executed / failed / rejected, else the newest. */
export function currentFixPlan(plans: FixPlan[] | undefined): FixPlan | null {
  const sorted = [...(plans ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  return sorted.find((p) => !TERMINAL_PLAN.has(p.status)) ?? sorted[0] ?? null;
}
