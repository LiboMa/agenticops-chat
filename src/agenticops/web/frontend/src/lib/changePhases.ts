import type { ChangeRequest } from "@/api/types";
import type { PhaseView, WaitingFor } from "@/lib/issuePhases";

export type ChangePhaseId = "request" | "review" | "plan" | "run" | "accept";
export type ChangePrimary = "startReview" | "answerReviewer" | "approveAndRun" | "retryExecution" | "markCompleted" | "copyAsNew" | null;
export type ChangeSub = "draft" | "reviewing" | "needsClarification" | "awaitingApproval" | "notQueued" | "executing"
  | "awaitingAcceptance" | "completed" | "failed" | "rolledBack" | "rejected" | "cancelled"
  | "unknown"; // a status this page does not know (a newer backend)
export interface ChangePhaseResult {
  current: ChangePhaseId;
  sub: ChangeSub;
  waitingFor: WaitingFor;
  primary: ChangePrimary;
  phases: PhaseView<ChangePhaseId>[];
  terminal: boolean;
}

export const CHANGE_PHASES: readonly ChangePhaseId[] = ["request", "review", "plan", "run", "accept"];

function open(current: ChangePhaseId, sub: ChangeSub, waitingFor: WaitingFor, primary: ChangePrimary): ChangePhaseResult {
  const at = CHANGE_PHASES.indexOf(current);
  return { current, sub, waitingFor, primary, terminal: false,
           phases: CHANGE_PHASES.map((id, i) => ({ id, state: i < at ? "done" : i === at ? "current" : "future" })) };
}

/** Spec §4 change table. A change that ended badly ends its phase list at the phase it ended on. */
function ended(at: ChangePhaseId, sub: ChangeSub): ChangePhaseResult {
  const idx = CHANGE_PHASES.indexOf(at);
  return { current: at, sub, waitingFor: null, primary: "copyAsNew", terminal: true,
           phases: CHANGE_PHASES.slice(0, idx + 1).map((id, i) => ({ id, state: i < idx ? "done" : "failed" })) };
}

export function changePhases(
  cr: Pick<ChangeRequest, "status" | "review_verdict" | "approved_at"> & Partial<Pick<ChangeRequest, "policy_action">>,
): ChangePhaseResult {
  const reviewPassed = cr.review_verdict === "approved_for_planning";
  switch (cr.status) {
    case "draft": return open("request", "draft", "requester", "startReview");
    case "under_review": return open("review", "reviewing", "sre_agent", null);
    case "needs_clarification": return open("review", "needsClarification", "requester", "answerReviewer");
    case "planned": return open("run", "awaitingApproval", "approver", "approveAndRun");
    case "approved": return open("run", "notQueued", "you", "retryExecution");
    case "executing": return open("run", "executing", "executor", null);
    case "needs_review": return open("accept", "awaitingAcceptance", "acceptor", "markCompleted");
    case "completed":
      return { current: "accept", sub: "completed", waitingFor: null, primary: null, terminal: true,
               phases: CHANGE_PHASES.map((id) => ({ id, state: "done" as const })) };
    case "failed": return ended("run", "failed");
    case "rolled_back": return ended("run", "rolledBack");
    // a policy block rejects at the review, after the verdict passed — no approver ever saw it
    case "rejected": return ended(reviewPassed && cr.policy_action !== "block" ? "run" : "review", "rejected");
    case "cancelled":
      return ended(cr.approved_at || reviewPassed ? "run" : cr.review_verdict ? "review" : "request", "cancelled");
    default: {
      // degrade, never throw: no button, nobody waited on, the phases there is data for read done
      const reached: Record<ChangePhaseId, boolean> = {
        request: true, review: !!cr.review_verdict, plan: reviewPassed, run: !!cr.approved_at, accept: false,
      };
      return { current: "request", sub: "unknown", waitingFor: null, primary: null, terminal: false,
               phases: CHANGE_PHASES.map((id) => ({ id, state: reached[id] ? "done" : "future" })) };
    }
  }
}
