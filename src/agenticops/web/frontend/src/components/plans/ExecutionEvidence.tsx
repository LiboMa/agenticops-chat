import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { resultRow, resultSummary, type ResultOutcome } from "@/lib/issueDetail";
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
        return (
          <div key={field}>
            <h4 className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-foreground">
              {t(label)}
              <span className="text-xs font-normal text-muted-foreground">
                {items.length === 0 ? t("evidence.none")
                  : (Object.keys(counts) as ResultOutcome[]).filter((k) => counts[k] > 0)
                      .map((k) => `${counts[k]} ${t(`evidence.outcome.${k}`)}`).join(" · ")}
              </span>
            </h4>
            {items.length > 0 && (
              <ol className="space-y-1">
                {items.map((item, i) => <ResultLine key={i} index={i + 1} item={item} />)}
              </ol>
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
