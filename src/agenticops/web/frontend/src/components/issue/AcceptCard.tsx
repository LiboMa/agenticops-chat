import type { FixExecution } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { VerificationChip } from "@/components/plans/VerificationChip";
import { formatFullDate } from "@/lib/formatDate";
import { isBlank } from "@/lib/issueDetail";

type T = (key: string) => string;

/** ④ Accept: the newest run's verdict and who accepted it. Accept / reject only for `pendingRun` (issueStatuses:
 *  the newest run, while the issue sits at fix_executed); the reason the status line already shows is not repeated. */
export function AcceptBody({ runs, loading, error, onRetryFetch, pendingRun, quietRunId, onAccept, onReject, t }: {
  runs: FixExecution[];          // newest first
  loading: boolean;
  error: Error | null;
  onRetryFetch: () => void;
  pendingRun: FixExecution | null;
  quietRunId: number | null;     // the run whose verification_reason the status line already shows
  onAccept: () => void;
  onReject: () => void;
  t: T;
}) {
  if (loading) return <Spinner label={t("common.loading")} />;
  // a failed fetch must not read as "not executed"
  if (error) return <ErrorBanner message={error.message} onRetry={onRetryFetch} actionLabel={t("common.retry")} />;
  const latest = runs[0] ?? null;
  if (!latest) return <p className="text-sm text-muted-foreground">{t("verification.noExecution")}</p>;
  const rows: [string, string | null][] = [
    ["verification.reason", latest.id === quietRunId ? null : latest.verification_reason],
    ["verification.acceptedBy", latest.accepted_by],
    ["verification.acceptedAt", latest.accepted_at && formatFullDate(latest.accepted_at)],
    ["verification.note", latest.acceptance_note],
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold text-foreground">{t("issues.executionN").replace("{n}", String(latest.id))}</h3>
        <VerificationChip status={latest.verification_status} />
        {pendingRun?.id === latest.id && (
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onAccept}
                    className="px-3 py-1.5 border border-emerald-600/40 text-emerald-600 dark:text-emerald-400 text-xs font-medium rounded-lg hover:bg-emerald-500/10 transition-colors">
              {t("workitem.primary.acceptResult")}
            </button>
            <button onClick={onReject}
                    className="px-3 py-1.5 border border-red-500/30 text-red-500 text-xs font-medium rounded-lg hover:bg-red-500/10 transition-colors">
              {t("verification.reject")}
            </button>
          </div>
        )}
      </div>
      {rows.some(([, v]) => !isBlank(v)) && (
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          {rows.filter(([, v]) => !isBlank(v)).map(([key, v]) => (
            <div key={key} className={key === "verification.reason" || key === "verification.note" ? "md:col-span-2" : undefined}>
              <dt className="text-muted-foreground">{t(key)}</dt>
              <dd className="text-foreground whitespace-pre-wrap break-words">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      {runs.length > 1 && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">{t("verification.history")}</h4>
          <ul className="space-y-2 text-sm">
            {runs.map((ex) => (
              <li key={ex.id} className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">#{ex.id}</span>
                <VerificationChip status={ex.verification_status} />
                {ex.id !== quietRunId && <span className="text-muted-foreground">{ex.verification_reason}</span>}
                {ex.accepted_by && (
                  <span className="text-xs text-muted-foreground">· {ex.accepted_by}: {ex.acceptance_note}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
