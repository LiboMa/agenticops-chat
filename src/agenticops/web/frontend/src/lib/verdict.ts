import type { LocationVerdict, RCAResult } from "@/api/types";

/** "Your verdict" (P9): one choice replaces 👍👎, the location's three buttons and False positive / Confirmed.
 *  It maps onto the two existing endpoints — POST /health-issues/{id}/rca-feedback, then /feedback. */
export type VerdictChoice = "correct" | "partial" | "rcaWrong" | "falsePositive";
export const VERDICT_CHOICES: readonly VerdictChoice[] = ["correct", "partial", "rcaWrong", "falsePositive"];

type LocInput = Pick<RCAResult, "location_status" | "location_verdict"> | null | undefined;

export interface VerdictRequests {
  rcaFeedback: { verdict?: "correct" | "incorrect"; location_verdict?: LocationVerdict; note?: string } | null;
  issueFeedback: { type: "confirmed" | "false_positive"; note?: string; confidence: number } | null;
}

/** The backend takes a location verdict only for a valid / partial location, and this block sends it once. */
export function locationJudgeable(rca: LocInput): boolean {
  return !!rca && (rca.location_status === "valid" || rca.location_status === "partial") && !rca.location_verdict;
}

export function choiceAvailable(choice: VerdictChoice, rca: LocInput): boolean {
  if (choice === "falsePositive") return true;
  if (!rca) return false;
  return choice === "partial" ? locationJudgeable(rca) : true;
}

export function noteRequired(choice: VerdictChoice): boolean {
  return choice === "rcaWrong" || choice === "falsePositive";
}

export function verdictRequests(choice: VerdictChoice, rca: LocInput, note: string): VerdictRequests {
  const n = note.trim();
  const withNote = <T extends object>(o: T) => (n ? { ...o, note: n } : o);
  const loc = locationJudgeable(rca);
  switch (choice) {
    case "correct":
      return { rcaFeedback: withNote({ verdict: "correct" as const, ...(loc ? { location_verdict: "correct" as const } : {}) }),
               issueFeedback: { type: "confirmed", confidence: 5 } };
    case "partial":
      return { rcaFeedback: withNote({ verdict: "correct" as const, location_verdict: "partial" as const }),
               issueFeedback: { type: "confirmed", confidence: 5 } };
    case "rcaWrong":
      return { rcaFeedback: withNote({ verdict: "incorrect" as const, ...(loc ? { location_verdict: "incorrect" as const } : {}) }),
               issueFeedback: null };
    case "falsePositive":
      return { rcaFeedback: null, issueFeedback: withNote({ type: "false_positive" as const, confidence: 4 }) };
  }
}

/** What a submit stopped at `failed` still has to send, when part of it already took effect: the root-cause
 *  verdict saved and the issue feedback failed → that feedback alone (the saved verdict is not sent twice).
 *  null when nothing took effect (the form submits again as it is) or nothing is left. */
export function remainingRequests(req: VerdictRequests, failed: "rcaFeedback" | "issueFeedback"): VerdictRequests | null {
  return failed === "issueFeedback" && req.rcaFeedback && req.issueFeedback
    ? { rcaFeedback: null, issueFeedback: req.issueFeedback } : null;
}
