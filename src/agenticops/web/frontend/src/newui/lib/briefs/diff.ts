import type { PlanLineDiff, PreviousPlanDiff } from "@/api/types";

/** What a fix plan changed relative to the plan before it on the same issue (N14), as the approve brief says it.
 *  The server compares by what would RUN (a step's command; a step without one, its words) — so reworded text
 *  around an unchanged command is not a line here, and «no line changed» is never said as «nothing changed». */

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
  /** identical = the same content hash · sameCommands = no step or rollback line differs, yet the content does
   *  (wording, checks, risk level) · sameCommandsUnknown = no line differs and nothing says whether the rest does ·
   *  changed = at least one line differs */
  verdict: "identical" | "sameCommands" | "sameCommandsUnknown" | "changed";
  steps: DiffPart;
  rollback: DiffPart;
  risk: { from: string; to: string } | null;
}

export function prevDiffVm(answer: PreviousPlanDiff | null | undefined, riskNow: string | null | undefined): PrevDiffVm | null {
  const prev = answer?.previous;
  if (!answer || !prev) return null;
  const reason = (prev.rejection_reason ?? "").trim();
  const ended = prev.status === "rejected" ? (prev.rejection_is_feedback && reason ? "feedback" : reason ? "byCode" : "rejected")
    : prev.status === "failed" ? "failed" : prev.status === "executed" ? "ran" : "other";
  const steps = partOf(answer.steps), rollback = partOf(answer.rollback);
  const verdict = answer.same_content === true ? "identical"
    : steps.lines.length || rollback.lines.length ? "changed"
    : answer.same_content === false ? "sameCommands" : "sameCommandsUnknown";
  return {
    previousId: prev.id, ended, status: prev.status, by: prev.rejected_by, at: prev.rejected_at, reason,
    otherDiagnosis: prev.same_diagnosis === false, verdict, steps, rollback,
    risk: prev.risk_level && riskNow && prev.risk_level !== riskNow ? { from: prev.risk_level, to: riskNow } : null,
  };
}
