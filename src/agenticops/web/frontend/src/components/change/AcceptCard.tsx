import type { ChangeStatus, FixExecution } from "@/api/types";
import { VerificationChip } from "@/components/plans/VerificationChip";
import { formatFullDate } from "@/lib/formatDate";
import { isBlank } from "@/lib/issueDetail";
import { fillPlaceholders } from "@/lib/placeholders";

type T = (key: string) => string;
type Note = { key: string; params?: Record<string, string> };

/** ⑤ Accept. Waiting for a person's verdict: the run's verdict, mark completed / failed (a reason is required;
 *  outlined, the status line holds the filled one). A run the system judged failed needs no acceptance — one
 *  sentence pointing at that run. Completed: the verdict and who accepted it. The verdict reason is left out when
 *  it IS the status line's sentence (`quietReason`). */
export function ChangeAcceptBody({ status, latestRun, acceptNote, quietReason, onCompleted, onFailed, busy, t }: {
  status: ChangeStatus;
  latestRun: FixExecution | null;
  acceptNote: Note | null;
  quietReason: boolean;
  onCompleted: () => void;
  onFailed: () => void;
  busy: boolean;
  t: T;
}) {
  const muted = "text-muted-foreground";
  const reason = latestRun && !quietReason && !isBlank(latestRun.verification_reason) ? latestRun.verification_reason : null;
  if (acceptNote && status !== "needs_review") {
    return (
      <p className={`text-sm ${muted}`}>
        {fillPlaceholders(t(acceptNote.key), acceptNote.params)}
      </p>
    );
  }
  const head = latestRun && (
    <div className="flex flex-wrap items-center gap-3">
      <h3 className="font-semibold text-foreground">{t("issues.executionN").replace("{n}", String(latestRun.id))}</h3>
      <VerificationChip status={latestRun.verification_status} />
    </div>
  );
  if (status === "needs_review") {
    return (
      <div className="space-y-3 text-sm">
        {head}
        {reason && <p className="text-foreground whitespace-pre-wrap break-words">{reason}</p>}
        <p className={muted}>{t("changes.needsReviewNote")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={onCompleted} disabled={busy}
                  className="px-4 py-2 border border-emerald-600/40 text-emerald-600 dark:text-emerald-400 text-sm font-medium rounded-lg hover:bg-emerald-500/10 disabled:opacity-50 transition-colors">
            {t("workitem.primary.markCompleted")}
          </button>
          <button onClick={onFailed} disabled={busy}
                  className="px-4 py-2 border border-red-500/30 text-red-500 text-sm font-medium rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors">
            {t("changes.markFailed")}
          </button>
        </div>
      </div>
    );
  }
  if (!latestRun) return <p className={`text-sm ${muted}`}>{t("changes.noAcceptance")}</p>;
  const rows: [string, string | null][] = [
    ["verification.reason", reason],
    ["verification.acceptedBy", latestRun.accepted_by],
    ["verification.acceptedAt", latestRun.accepted_at && formatFullDate(latestRun.accepted_at)],
    ["verification.note", latestRun.acceptance_note],
  ];
  const shown = rows.filter(([, v]) => !isBlank(v));
  return (
    <div className="space-y-4 text-sm">
      {head}
      {shown.length > 0 && (
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {shown.map(([key, v]) => (
            <div key={key} className={key === "verification.reason" || key === "verification.note" ? "md:col-span-2" : undefined}>
              <dt className={muted}>{t(key)}</dt>
              <dd className="text-foreground whitespace-pre-wrap break-words">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
