import type { FixExecution, PostCheckBinding } from "@/api/types";
import { resultRow, type ResultOutcome } from "@/lib/issueDetail";

export interface PostCheckRow {
  key: string;
  /** pc-n for a declared check (or the id a stray result named); "—" for a result with no check_id. */
  label: string;
  title: string;
  outcome: ResultOutcome | null;
  problem: PostCheckBinding["problem"];
  /** How many results named this check (2+ = duplicate). */
  count: number;
  output: string;
}

const idOf = (item: unknown): string | null => {
  if (item === null || typeof item !== "object" || Array.isArray(item)) return null;
  const v = (item as Record<string, unknown>).check_id;
  return v == null || String(v).trim() === "" ? null : String(v).trim().toLowerCase();
};

/** The post-check section of a run, read through the server's binding (the verdict's own pairing).
 *  legacy: the run was recorded before results carried check_ids — show them as reported, in order. */
export function postCheckRows(ex: FixExecution): { legacy: boolean; rows: PostCheckRow[] } {
  const results = ex.post_check_results ?? [];
  const binding = ex.post_check_binding ?? [];
  if (binding.length === 0 || (results.length > 0 && results.every((r) => idOf(r) === null))) {
    return { legacy: true, rows: [] };
  }
  const declared = new Set(binding.filter((b) => b.problem !== "undeclared" && b.problem !== "unbound").map((b) => b.check_id));
  const strays = results.filter((r) => !declared.has(idOf(r)));
  let stray = 0;
  const rows = binding.map((b, i): PostCheckRow => {
    const isStray = b.problem === "undeclared" || b.problem === "unbound";
    const source = isStray ? strays[stray++] : results.find((r) => idOf(r) === b.check_id);
    const r = source === undefined ? null : resultRow(source);
    return {
      key: `${b.check_id ?? "stray"}-${i}`,
      label: b.check_id ?? "—",
      title: b.check ?? r?.title ?? "",
      outcome: b.result_status,
      problem: b.problem,
      count: b.results,
      output: r?.output ?? "",
    };
  });
  return { legacy: false, rows };
}

/** The section's tally for a bound run, one count per declared check (a duplicate counts once, by its outcome);
 *  a declared check with no result is counted as such — never folded into the passes the raw list would show. */
export function boundSummary(rows: PostCheckRow[]): { outcomes: Partial<Record<ResultOutcome, number>>; missing: number } {
  const outcomes: Partial<Record<ResultOutcome, number>> = {};
  let missing = 0;
  for (const r of rows) {
    if (r.problem === "missing") missing++;
    else if (r.outcome) outcomes[r.outcome] = (outcomes[r.outcome] ?? 0) + 1;
  }
  return { outcomes, missing };
}
