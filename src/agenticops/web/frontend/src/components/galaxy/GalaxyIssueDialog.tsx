import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import type { Anomaly } from "@/api/types";

const SEV_COLOR: Record<string, string> = {
  critical: "#d03b3b", high: "#fab219", medium: "#fab219", low: "#7d8590",
};

/**
 * In-place issue detail dialog for the Galaxy panel — no route change, so the
 * operator keeps the starfield + node panel context and can ESC back to check
 * the next issue. ESC closes ONLY this dialog (parent panel suppresses its own
 * ESC while this is mounted).
 */
export function GalaxyIssueDialog({ issue, onClose }: { issue: Anomaly; onClose: () => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const rca = useAnomalyRca(issue.id);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    };
    // capture phase so we intercept ESC before the panel/window listeners
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg mx-4
                      max-h-[80vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150"
           role="dialog" aria-modal="true">
        {/* Header: severity stripe + badges + title */}
        <div className="sticky top-0 bg-card border-b border-border px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="mt-1.5 h-3 w-3 rounded-full shrink-0 ring-4 ring-offset-0"
                  style={{ background: SEV_COLOR[issue.severity] || "#7d8590",
                           boxShadow: `0 0 0 4px ${SEV_COLOR[issue.severity]}22` }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
                      style={{ background: `${SEV_COLOR[issue.severity]}22`, color: SEV_COLOR[issue.severity] }}>
                  {issue.severity}
                </span>
                <IssueStatusBadge status={issue.status} />
              </div>
              <h3 className="text-[15px] font-semibold text-foreground leading-snug break-words">{issue.title}</h3>
            </div>
            <button onClick={onClose} aria-label="close"
                    className="text-muted-foreground hover:text-foreground text-lg leading-none shrink-0 -mt-1">✕</button>
          </div>
        </div>

        <div className="px-5 py-4 space-y-5">
          {/* Root cause — most actionable, surfaced first */}
          {rca.data?.root_cause && (
            <section className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3.5">
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-amber-500 text-sm">◆</span>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                  {t("galaxy.rootCause")}
                </span>
              </div>
              <p className="text-sm text-foreground leading-relaxed break-words">{rca.data.root_cause}</p>
              {rca.data.recommendations && rca.data.recommendations.length > 0 && (
                <ul className="mt-2.5 space-y-1">
                  {rca.data.recommendations.slice(0, 3).map((rec, i) => (
                    <li key={i} className="flex gap-2 text-xs text-muted-foreground">
                      <span className="text-emerald-500 shrink-0">→</span>
                      <span className="break-words">{rec}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {/* Description */}
          {issue.description && (
            <section>
              <SectionTitle>{t("galaxy.description")}</SectionTitle>
              <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap break-words">
                {issue.description}
              </p>
            </section>
          )}

          {/* Metric callout — the numbers that triggered it, made prominent */}
          {issue.metric_name && issue.actual_value != null && (
            <section className="flex items-baseline gap-4 rounded-lg bg-muted/40 px-3.5 py-2.5">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{issue.metric_name}</div>
                <div className="text-lg font-semibold text-foreground tabular-nums">{issue.actual_value}</div>
              </div>
              {issue.expected_value != null && (
                <div className="text-xs text-muted-foreground">
                  {t("galaxy.expected")} <span className="tabular-nums">{issue.expected_value}</span>
                  {issue.deviation_percent != null && (
                    <span className="ml-1 text-amber-600 dark:text-amber-400">
                      ({issue.deviation_percent > 0 ? "+" : ""}{issue.deviation_percent}%)
                    </span>
                  )}
                </div>
              )}
            </section>
          )}

          {/* Metadata definition grid */}
          <section>
            <SectionTitle>{t("galaxy.details")}</SectionTitle>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
              <Field k={t("galaxy.resourceId")} v={issue.resource_id} />
              <Field k={t("galaxy.type")} v={issue.resource_type} />
              <Field k={t("galaxy.region")} v={issue.region} />
              <Field k={t("issues.detected")} v={new Date(issue.detected_at).toLocaleString()} />
            </dl>
          </section>
        </div>

        <div className="sticky bottom-0 bg-card border-t border-border px-5 py-3 flex justify-end items-center">
          <button onClick={() => navigate(`/app/issues/${issue.id}`)}
                  className="text-xs text-primary hover:underline">{t("galaxy.openFullIssue")} →</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">{children}</div>;
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-foreground break-all text-right">{v}</dd>
    </>
  );
}
