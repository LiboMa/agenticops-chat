import type { UiAction } from "@/api/types";

/** The named action from a plan's / change's available_actions (services/ui_actions), or null. */
export function findAction(actions: UiAction[] | undefined | null, name: string): UiAction | null {
  return actions?.find((a) => a.action === name) ?? null;
}

export interface ApprovalCopy { titleKey: string; buttonKey: string; noteKey: string }

/** What an approval says it does (MVP-2.7.0 S3): "run" only when the server will queue the run. An unknown effect
 *  (an older server) is the neutral "Approve" with a note that the server's settings decide. */
export function approvalCopy(effect: string | null | undefined): ApprovalCopy {
  if (effect === "approve_and_queue_execution") return { titleKey: "approval.title.run", buttonKey: "approval.button.run", noteKey: "approval.note.run" };
  return { titleKey: "approval.title.only", buttonKey: "approval.button.only",
           noteKey: effect === "approve_only" ? "approval.note.only" : "approval.note.unknown" };
}

/** ReasonDialog's confirm: not while busy, not without a required reason, not before the acknowledgement. */
export function canConfirm(o: { busy: boolean; required: boolean; reason: string; ack: boolean; acked: boolean }): boolean {
  return !o.busy && (!o.required || o.reason.trim() !== "") && (!o.ack || o.acked);
}

/** What the issue's run card promises before there is a plan (final review U8): an automatic run only when auto-fix,
 *  the executor and L0/L1 auto-approval are all on (pipeline_service.trigger_auto_approve / trigger_auto_execute). */
export function runHintKey(s: { auto_fix_enabled?: boolean; executor_enabled?: boolean; executor_auto_approve_l0_l1?: boolean } | undefined): string {
  if (!s) return "workitem.future.issue.runNeutral";
  if (!s.auto_fix_enabled || !s.executor_enabled) return "workitem.future.issue.runManual";
  return s.executor_auto_approve_l0_l1 ? "workitem.future.issue.run" : "workitem.future.issue.runApprove";
}
