import type { PlanLineDiff, PreviousPlanDiff } from "@/api/types";

/** What a fix plan changed relative to the plan before it on the same issue (N14), as the approve brief says it.
 *  The server compares by what would RUN (a step's command; a step without one, its words) — so reworded text
 *  around an unchanged command is not a line here, and «no line changed» is never said as «nothing changed».
 *  Each part is said on its own line — steps, rollback, checks, risk level — never summed up in one sentence: a
 *  rollback written as a sentence has no line, and «no command of the rollback changed» was said of one that had
 *  been rewritten (round-2 review). */

export interface DiffLine {
  kind: "add" | "del" | "chg";
  /** the step's number — in this plan for add / chg, in the previous plan for del */
  n: number;
  text: string;
  /** chg: what the previous plan had there, and its number there */
  was?: string;
  wasN?: number;
}

export interface DiffPart { lines: DiffLine[]; unchanged: number }

/** One list's changes as lines in reading order: by step number, a removed step where it was — before whatever
 *  took its number. */
export function partOf(d: PlanLineDiff | null | undefined): DiffPart {
  if (!d) return { lines: [], unchanged: 0 };
  const rows: { at: number; line: DiffLine }[] = [
    ...d.modified.map((m) => ({ at: m.step, line: { kind: "chg" as const, n: m.step, text: m.now, was: m.previous, wasN: m.previous_step } })),
    ...d.removed.map((r) => ({ at: r.previous_step - 0.5, line: { kind: "del" as const, n: r.previous_step, text: r.text } })),
    ...d.added.map((a) => ({ at: a.step, line: { kind: "add" as const, n: a.step, text: a.text } })),
  ];
  // a modified step and a removed one can claim the same place (step 2 changed, old step 2 … ): the change first
  return { lines: rows.sort((x, y) => Math.ceil(x.at) - Math.ceil(y.at) || y.at - x.at).map((r) => r.line), unchanged: d.unchanged };
}

/** A list of changes this long or shorter is shown open; a longer one starts folded under its numbers (a plan
 *  rewritten from top to bottom is read as a plan, not as a diff). */
export const OPEN_UP_TO = 4;

/** One list's changes as numbers: how many lines changed, were added, were removed, stayed — whether the list of
 *  lines starts open, and whether there was anything to compare at all (two rollbacks written as prose have no
 *  line on either side: that is «cannot be compared», never «unchanged»). */
export function tallyOf(part: DiffPart): { chg: number; add: number; del: number; same: number; open: boolean; comparable: boolean } {
  const n = (k: DiffLine["kind"]) => part.lines.filter((l) => l.kind === k).length;
  return { chg: n("chg"), add: n("add"), del: n("del"), same: part.unchanged, open: part.lines.length <= OPEN_UP_TO,
           comparable: part.lines.length + part.unchanged > 0 };
}

export interface PrevDiffVm {
  previousId: number;
  /** what became of the plan before: a person sent it back and said why (`reason` is quoted) · code sent it back
   *  (`reason` is the code's) · sent back with no reason · its run failed · it ran · anything else (`status`) */
  ended: "feedback" | "byCode" | "rejected" | "failed" | "ran" | "other";
  status: string;
  by: string | null;
  at: string | null;
  reason: string;
  /** the two plans were written from different diagnoses (known, not guessed) */
  otherDiagnosis: boolean;
  /** identical = the same content hash · changed = something this page compares differs (a step or rollback line,
   *  the rollback's text, the checks, the risk level) · unexplained = the content differs and nothing this page
   *  compares does (the account the issue belongs to is part of the content too) · unknown = nothing compared
   *  differs and nothing says whether the content does */
  verdict: "identical" | "changed" | "unexplained" | "unknown";
  steps: DiffPart;
  rollback: DiffPart;
  /** a rollback with no line on either side (a sentence): is its text the same, or was it rewritten — null when
   *  it has lines (they are compared) or the server did not say */
  rollbackText: "same" | "rewritten" | null;
  /** the declared checks, [the previous plan, this plan]: the same · another number · the same number, other content.
   *  `fewerAfter` = fewer checks after a run than before: an easier «passed». null = the server did not say */
  checks: { how: "same" | "count" | "content"; pre: [number, number]; post: [number, number]; fewerAfter: boolean } | null;
  risk: { from: string; to: string } | null;
}

export function prevDiffVm(answer: PreviousPlanDiff | null | undefined, riskNow: string | null | undefined): PrevDiffVm | null {
  const prev = answer?.previous;
  if (!answer || !prev) return null;
  const reason = (prev.rejection_reason ?? "").trim();
  const ended = prev.status === "rejected" ? (prev.rejection_is_feedback && reason ? "feedback" : reason ? "byCode" : "rejected")
    : prev.status === "failed" ? "failed" : prev.status === "executed" ? "ran" : "other";
  const steps = partOf(answer.steps), rollback = partOf(answer.rollback);
  const rollbackText = tallyOf(rollback).comparable || typeof answer.rollback_same !== "boolean" ? null
    : answer.rollback_same ? "same" : "rewritten";
  const c = answer.checks;
  const checks = !c ? null : {
    how: c.same ? "same" as const : c.pre[0] !== c.pre[1] || c.post[0] !== c.post[1] ? "count" as const : "content" as const,
    pre: c.pre, post: c.post, fewerAfter: c.post[1] < c.post[0],
  };
  const risk = prev.risk_level && riskNow && prev.risk_level !== riskNow ? { from: prev.risk_level, to: riskNow } : null;
  const differs = steps.lines.length > 0 || rollback.lines.length > 0 || rollbackText === "rewritten"
    || (checks !== null && checks.how !== "same") || risk !== null || answer.risk_same === false;
  // «everything this page compares is the same» can only be said when the server told us about all of it
  const told = typeof answer.rollback_same === "boolean" && !!c && typeof answer.risk_same === "boolean";
  const verdict = answer.same_content === true ? "identical" : differs ? "changed"
    : answer.same_content === false && told ? "unexplained" : "unknown";
  return {
    previousId: prev.id, ended, status: prev.status, by: prev.rejected_by, at: prev.rejected_at, reason,
    otherDiagnosis: prev.same_diagnosis === false, verdict, steps, rollback, rollbackText, checks, risk,
  };
}
