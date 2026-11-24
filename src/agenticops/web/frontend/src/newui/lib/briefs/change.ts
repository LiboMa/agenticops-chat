import type { ChangeRequest } from "@/api/types";
import { unresolvedHints } from "@/lib/changeDetail";
import type { StepVm } from "./plan";

/** A change request as its briefs show it. */

export interface RequestVm {
  text: string;
  why: string;
  by: string;
  emergency: boolean;
  /** the resources the request resolved to */
  targets: { id: string; type: string; region: string | null }[];
  /** what the requester named that matched no resource */
  unresolved: string[];
  /** the requester's own steps; no tier — only an implementation plan's steps are classified */
  proposed: StepVm[];
}

export function requestVm(cr: ChangeRequest): RequestVm {
  return {
    text: cr.description || cr.title,
    why: cr.justification ?? "",
    by: cr.requested_by,
    emergency: cr.requested_change_type === "emergency",
    targets: (cr.target_resources ?? []).map((r) => ({ id: r.resource_id, type: r.resource_type, region: r.region })),
    unresolved: unresolvedHints(cr),
    proposed: (cr.proposed_steps ?? []).map((s) => ({ say: s.action ?? "", cmd: s.command || null, tier: null })),
  };
}

/** POST /api/changes/{id}/clarify takes one message of at most this many characters. */
export const CLARIFY_MAX = 4000;

/** The answers as the one message the server takes: each answer under its numbered question. Whole — a message
 *  that is too long is not sent (clarifyOverflow), never cut: the tail it would lose is the last answers. */
export function clarifyMessage(questions: string[], answers: string[]): string {
  return questions.length
    ? questions.map((q, i) => `${i + 1}. ${q}\n   ${(answers[i] ?? "").trim()}`).join("\n\n")
    : (answers[0] ?? "").trim();
}

/** By how many characters the message is over what the server takes; 0 = it fits. */
export function clarifyOverflow(questions: string[], answers: string[]): number {
  return Math.max(0, clarifyMessage(questions, answers).length - CLARIFY_MAX);
}

/** Every question answered — with no specific question, the one free answer — and the whole fits in one message. */
export function canClarify(questions: string[], answers: string[]): boolean {
  const answered = questions.length ? questions.every((_, i) => !!answers[i]?.trim()) : !!answers[0]?.trim();
  return answered && clarifyOverflow(questions, answers) === 0;
}
