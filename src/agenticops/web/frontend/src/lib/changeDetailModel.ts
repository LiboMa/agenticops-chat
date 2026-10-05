import type { ChangeRequestDetail, FixExecution, FixPlan } from "@/api/types";
import { activeChangePlan, changeHeadline } from "@/lib/changeDetail";
import { newestFirst } from "@/lib/issueDetail";
import { changePhases, type ChangePhaseResult } from "@/lib/changePhases";

export type ChangeMenuItem = "reject" | "cancel" | "copyAsNew" | "restartReview";
export interface ChangeDetailModel {
  phase: ChangePhaseResult;
  statusKey: string;
  tone: "info" | "warn" | "bad" | "ok";
  reason: string | null;
  waitingKey: string | null;
  primaryKey: string | null;
  plan: FixPlan | null;
  reviewPlan: FixPlan | null; // the list ends at ② before ③ is drawn (a policy block): its plan, read-only, in ②
  latestRun: FixExecution | null;
  runs: FixExecution[];
  acceptNote: { key: string; params?: Record<string, string> } | null;
  menu: ChangeMenuItem[];
  quietRunError: boolean; // the latest run's error_message IS the status line's sentence: ④ does not repeat it
  quietReviewReasons: boolean; // the review rejected it and its reasons ARE the status line's sentence: ② does not list them
  quietAcceptReason: boolean; // the latest run's verification_reason IS the status line's sentence: ⑤ does not repeat it
}

const CANCELLABLE = ["draft", "needs_clarification", "planned", "approved"];
const COPYABLE = ["needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"];

/** ChangeDetail's view model. The reason (changeHeadline's — the same sentence ContextPanel shows) lives only in
 *  the status line; a run the system judged failed is pointed at from the accept card, not repeated (P3). */
export function changeDetailModel(cr: ChangeRequestDetail): ChangeDetailModel {
  const runs = newestFirst(cr.executions);
  const latestRun = runs[0] ?? null;
  const phase = changePhases(cr);
  const reason = changeHeadline(cr, latestRun).reason;
  // "the system judged it failed" only for the system's terminal verdict. A succeeded run with a failed verdict
  // (a post-check failed) went to needs_review and a person decided it; resolve_review stamps only a pending run,
  // so that run's accepted_by stays empty — its status tells it apart. A person's acceptance sets accepted_by.
  const failedRun = (cr.status === "failed" || cr.status === "rolled_back") && latestRun !== null
    && latestRun.verification_status === "failed" && !latestRun.accepted_by && latestRun.status !== "succeeded";
  const plan = activeChangePlan(cr.plans);
  const endsAtReview = phase.terminal && !phase.phases.some((p) => p.id === "plan");
  const menu: ChangeMenuItem[] = [
    ...(cr.status === "under_review" ? ["restartReview" as const] : []),
    ...(cr.status === "planned" ? ["reject" as const] : []),
    ...(CANCELLABLE.includes(cr.status) ? ["cancel" as const] : []),
    ...(COPYABLE.includes(cr.status) && phase.primary !== "copyAsNew" ? ["copyAsNew" as const] : []),
  ];
  return {
    phase,
    statusKey: phase.sub === "unknown" ? "workitem.sub.unknown" : `changes.status.${cr.status}`,
    tone: phase.terminal && phase.sub !== "completed" ? "bad"
      : phase.sub === "completed" ? "ok"
      : ["needsClarification", "awaitingApproval", "notQueued", "awaitingAcceptance"].includes(phase.sub) ? "warn" : "info",
    reason,
    waitingKey: phase.waitingFor ? `workitem.wait.${phase.waitingFor}` : null,
    primaryKey: phase.primary ? `workitem.primary.${phase.primary}` : null,
    plan,
    reviewPlan: endsAtReview ? plan : null,
    latestRun,
    runs,
    acceptNote: failedRun ? { key: "workitem.accept.systemFailed", params: { n: String(latestRun.id) } } : null,
    menu,
    quietRunError: reason !== null && reason === latestRun?.error_message,
    // the backend writes a review's rejection_reason as its reasons joined with "; " (change_service.submit_review)
    quietReviewReasons: cr.status === "rejected" && cr.review_reasons.length > 0 && reason === cr.review_reasons.join("; "),
    quietAcceptReason: reason !== null && reason === latestRun?.verification_reason,
  };
}
