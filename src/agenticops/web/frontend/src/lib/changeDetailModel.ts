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
  latestRun: FixExecution | null;
  runs: FixExecution[];
  acceptNote: { key: string; params?: Record<string, string> } | null;
  menu: ChangeMenuItem[];
  quietRunError: boolean; // the latest run's error_message IS the status line's sentence: ④ does not repeat it
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
  const failedRun = latestRun && latestRun.verification_status === "failed";
  const menu: ChangeMenuItem[] = [
    ...(cr.status === "under_review" ? ["restartReview" as const] : []),
    ...(cr.status === "planned" ? ["reject" as const] : []),
    ...(CANCELLABLE.includes(cr.status) ? ["cancel" as const] : []),
    ...(COPYABLE.includes(cr.status) && phase.primary !== "copyAsNew" ? ["copyAsNew" as const] : []),
  ];
  return {
    phase,
    statusKey: `changes.status.${cr.status}`,
    tone: phase.terminal && phase.sub !== "completed" ? "bad"
      : phase.sub === "completed" ? "ok"
      : ["needsClarification", "awaitingApproval", "notQueued", "awaitingAcceptance"].includes(phase.sub) ? "warn" : "info",
    reason,
    waitingKey: phase.waitingFor ? `workitem.wait.${phase.waitingFor}` : null,
    primaryKey: phase.primary ? `workitem.primary.${phase.primary}` : null,
    plan: activeChangePlan(cr.plans),
    latestRun,
    runs,
    acceptNote: failedRun ? { key: "workitem.accept.systemFailed", params: { n: String(latestRun!.id) } } : null,
    menu,
    quietRunError: reason !== null && reason === latestRun?.error_message,
  };
}
