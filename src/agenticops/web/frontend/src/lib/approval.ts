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
