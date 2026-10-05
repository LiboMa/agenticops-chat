import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { resultRow, resultSummary, type ResultOutcome } from "@/lib/issueDetail";
import { boundSummary, postCheckRows, type PostCheckRow } from "@/lib/postChecks";
import type { FixExecution } from "@/api/types";

const OUTCOME_CHIP: Record<ResultOutcome, string> = {
  pass: "bg-green-500/20 text-green-500",
  warning: "bg-amber-500/20 text-amber-500",
  fail: "bg-red-500/20 text-red-500",
  missing: "bg-secondary text-muted-foreground",
};

const SECTIONS = [
  ["pre_check_results", "issues.preChecks"],
  ["step_results", "issues.steps"],
  ["post_check_results", "issues.postChecks"],
  ["rollback_results", "issues.rollbackPlan"],
] as const;

/** What one run actually did: its pre-check / step / post-check / rollback results, each with its whole output.
 *  Shared by IssueDetail and ChangeDetail; the Card stays in the caller. `showError={false}` leaves the run's
 *  error out — a page whose status line already carries that sentence shows it once (P3). */
export function ExecutionEvidence({ execution: ex, showError = true }: { execution: FixExecution; showError?: boolean }) {
  const { t } = useLocale();
  return (
    <div className="space-y-4">
      {showError && ex.error_message && (
        <p className="rounded bg-red-500/10 p-2 text-sm text-red-500 whitespace-pre-wrap break-words">{ex.error_message}</p>
      )}
      {SECTIONS.map(([field, label]) => {
        const items = ex[field] ?? [];
        const counts = resultSummary(items);
        const bound = field === "post_check_results" ? postCheckRows(ex) : null;
        return (
          <div key={field}>
            <h4 className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-foreground">
              {t(label)}
              <span className="text-xs font-normal text-muted-foreground">
                {bound && !bound.legacy ? boundTally(bound.rows, t)
                  : items.length === 0 ? t("evidence.none")
                  : (Object.keys(counts) as ResultOutcome[]).filter((k) => counts[k] > 0)
                      .map((k) => `${counts[k]} ${t(`evidence.outcome.${k}`)}`).join(" · ")}
              </span>
            </h4>
            {bound && !bound.legacy ? (
              <ol className="space-y-1">
                {bound.rows.map((row) => <BoundCheckLine key={row.key} row={row} />)}
              </ol>
            ) : items.length > 0 && (
              <>
                {bound && (ex.post_check_binding?.length ?? 0) > 0 && (
                  <p className="mb-1 text-xs text-muted-foreground">{t("evidence.legacyUnbound")}</p>
                )}
                <ol className="space-y-1">
                  {items.map((item, i) => <ResultLine key={i} index={i + 1} item={item} />)}
                </ol>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ResultLine({ index, item }: { index: number; item: unknown }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const r = resultRow(item);
  return (
    <li className="rounded border border-border/60 text-xs">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} disabled={!r.output}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left enabled:hover:bg-secondary">
        <span className="font-mono text-muted-foreground">{index}.</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${OUTCOME_CHIP[r.outcome]}`}>
          {t(`evidence.outcome.${r.outcome}`)}
        </span>
        <span className="flex-1 truncate font-mono text-foreground">{r.title || "—"}</span>
        {r.output && <span className="text-muted-foreground">{open ? t("issues.collapse") : t("issues.expand")}</span>}
      </button>
      {open && r.output && (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all border-t border-border/60 bg-secondary/50 p-2 font-mono">
          {r.output}
        </pre>
      )}
    </li>
  );
}

/** "1 pass · 1 no result": the tally of a bound run, per declared check (lib/postChecks.boundSummary). */
function boundTally(rows: PostCheckRow[], t: (k: string) => string): string {
  const { outcomes, missing } = boundSummary(rows);
  const parts = (Object.keys(outcomes) as ResultOutcome[]).map((k) => `${outcomes[k]} ${t(`evidence.outcome.${k}`)}`);
  if (missing) parts.push(`${missing} ${t("evidence.problem.missing")}`);
  return parts.join(" · ") || t("evidence.none");
}

/** One declared post-check and what was reported for it (or a stray result): the problem, when there is one,
 *  is said in words next to the outcome — it is what the verdict's reason ("no result for post-check pc-2") names. */
function BoundCheckLine({ row }: { row: PostCheckRow }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const problem = row.problem === "duplicate"
    ? t("evidence.problem.duplicate").replace("{n}", String(row.count))
    : row.problem ? t(`evidence.problem.${row.problem}`) : "";
  return (
    <li className="rounded border border-border/60 text-xs">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} disabled={!row.output}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left enabled:hover:bg-secondary">
        <span className="font-mono text-muted-foreground">{row.label}</span>
        {row.outcome && (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${OUTCOME_CHIP[row.outcome]}`}>
            {t(`evidence.outcome.${row.outcome}`)}
          </span>
        )}
        {problem && (
          <span className="rounded border border-amber-500/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
            {problem}
          </span>
        )}
        <span className="flex-1 truncate text-foreground">{row.title || "—"}</span>
        {row.output && <span className="text-muted-foreground">{open ? t("issues.collapse") : t("issues.expand")}</span>}
      </button>
      {open && row.output && (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all border-t border-border/60 bg-secondary/50 p-2 font-mono">
          {row.output}
        </pre>
      )}
    </li>
  );
}
