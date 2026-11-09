import type { ReactNode } from "react";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import type { PhaseState } from "@/lib/issuePhases";
import type { RunSummary, CheckState } from "@/lib/runSummary";

const CHECK_TONE: Record<CheckState, StatusTone> = { passed: "ok", failed: "danger", warning: "warn", pending: "warn" };

/** The work item's first screen (MVP-2.8.0 S2), above its phase cards: where it stands on the step bar, who it
 *  waits on, for how long, which plan version — then the latest run (or, before any run, the diagnosis evidence)
 *  and one way down to the full card. The status line above keeps the one primary action. */
export function WorkSummary({ steps, facts, expand, t, children }: {
  steps: { id: string; label: string; state: PhaseState }[];
  facts: { owner: string | null; waiting: string | null; plan: string | null };
  expand: { label: string; onClick: () => void } | null;
  t: (k: string) => string;
  children: ReactNode;
}) {
  return (
    <section aria-label={t("workitem.summary.title")} className="rounded-lg border border-border bg-card">
      <ol className="flex flex-wrap gap-x-6 gap-y-2 border-b border-border px-4 py-3 text-sm">
        {steps.map((s, i) => (
          <li key={s.id} aria-current={s.state === "current" ? "step" : undefined} className="flex items-center gap-2">
            <span aria-hidden className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
              s.state === "done" ? "bg-status-ok/10 text-status-ok"
                : s.state === "failed" ? "bg-status-danger/10 text-status-danger"
                : s.state === "current" ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground"}`}>
              {s.state === "done" ? "✓" : s.state === "failed" ? "!" : i + 1}
            </span>
            <span className={s.state === "current" ? "font-medium text-primary" : s.state === "future" ? "text-muted-foreground" : "text-foreground"}>
              {s.label}
              <span className="sr-only"> · {t(`workitem.summary.state.${s.state}`)}</span>
            </span>
          </li>
        ))}
      </ol>
      <dl className="grid grid-cols-1 gap-3 border-b border-border px-4 py-3 text-sm sm:grid-cols-3">
        {([["owner", facts.owner], ["waiting", facts.waiting], ["plan", facts.plan]] as const).map(([k, v]) => (
          <div key={k} className="min-w-0 sm:border-l sm:border-border sm:pl-3 first:sm:border-l-0 first:sm:pl-0">
            <dt className="text-xs text-muted-foreground">{t(`workitem.summary.${k}`)}</dt>
            <dd className="mt-0.5 font-medium text-foreground [overflow-wrap:anywhere]">{v ?? "—"}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-3 px-4 py-3">
        {children}
        {expand && (
          <button type="button" onClick={expand.onClick} className="text-sm font-medium text-primary hover:underline">
            ▸ {expand.label}
          </button>
        )}
      </div>
    </section>
  );
}

/** The latest run: «8 / 8 steps done», the approval binding, each declared check, the warnings. */
export function RunSummaryBlock({ summary, t }: { summary: RunSummary; t: (k: string) => string }) {
  const binding = summary.planId != null
    ? [`Plan #${summary.planId}`, `v${summary.version}`, summary.hash8 && `hash ${summary.hash8}`].filter(Boolean).join(" · ")
    : null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{t("workitem.summary.latestRun")}</h3>
        <StatusText tone={summary.stepsDone === summary.stepsTotal ? "ok" : "warn"} className="text-xs">
          {t("workitem.summary.steps").replace("{done}", String(summary.stepsDone)).replace("{total}", String(summary.stepsTotal))}
        </StatusText>
      </div>
      {binding && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono">{binding}</span>
          {summary.matchesApproved != null && (
            <StatusText tone={summary.matchesApproved ? "ok" : "danger"}>
              {t(summary.matchesApproved ? "plan.hashMatches" : "plan.hashDrifted")}
            </StatusText>
          )}
        </p>
      )}
      {summary.checks.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {summary.checks.map((c, i) => (
            <li key={`${c.id ?? "x"}-${i}`} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 [overflow-wrap:anywhere]">
                {c.id && <span className="mr-1.5 font-mono text-xs text-muted-foreground">{c.id}</span>}{c.label}
              </span>
              <StatusText tone={CHECK_TONE[c.state]} className="shrink-0 text-xs">{t(`workitem.check.${c.state}`)}</StatusText>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Before any run: what the diagnosis rests on — the resource anchor, the human verdict and the model's confidence,
 *  each said apart (a model's confidence is never shown as the person's verdict). */
export function DiagnosisEvidence({ anchorStatus, humanVerdict, confidence, t }: {
  anchorStatus: string | null | undefined; humanVerdict: string | null | undefined; confidence: number | null | undefined;
  t: (k: string) => string;
}) {
  const rows: { key: string; tone: StatusTone; text: string }[] = [
    anchorStatus === "anchored"
      ? { key: "anchor", tone: "ok", text: t("workitem.evidence.anchored") }
      : { key: "anchor", tone: "warn", text: t("workitem.evidence.unanchored") },
    humanVerdict === "correct" ? { key: "verdict", tone: "ok", text: t("workitem.evidence.verdictCorrect") }
      : humanVerdict === "incorrect" ? { key: "verdict", tone: "danger", text: t("workitem.evidence.verdictIncorrect") }
      : { key: "verdict", tone: "neutral", text: t("workitem.evidence.noVerdict") },
  ];
  if (typeof confidence === "number") {
    rows.push({ key: "confidence", tone: "info",
                text: t("workitem.evidence.confidence").replace("{pct}", String(Math.round(confidence * 100))) });
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground">{t("workitem.evidence.title")}</h3>
      <ul className="divide-y divide-border rounded-md border border-border">
        {rows.map((r) => (
          <li key={r.key} className="px-3 py-2 text-sm"><StatusText tone={r.tone}>{r.text}</StatusText></li>
        ))}
      </ul>
    </div>
  );
}
