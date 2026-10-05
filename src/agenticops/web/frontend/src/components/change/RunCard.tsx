import type { ChangeRequestDetail, FixExecution, FixPlan } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { RunList } from "@/components/workitem/RunList";
import { formatFullDate } from "@/lib/formatDate";
import { fillPlaceholders } from "@/lib/placeholders";
import { shortHash } from "@/lib/plans";

type T = (key: string) => string;
type Note = { key: string; params?: Record<string, string> };

const IN_FLIGHT = ["pending", "running"];
// Join the present, non-empty parts with " · " (no dangling separators).
const joinDot = (parts: Array<string | null | undefined | false>): string =>
  parts.filter((x): x is string => typeof x === "string" && x.length > 0).join(" · ");

/** Who rejected or cancelled it, and when. The reason is the status line's sentence, so it is not repeated here. */
export function ClosedRecord({ cr, t }: { cr: ChangeRequestDetail; t: T }) {
  if (!cr.rejected_by || (cr.status !== "rejected" && cr.status !== "cancelled")) return null;
  return (
    <p className="text-sm text-red-500">
      {t(`changes.status.${cr.status}`)}: {joinDot([cr.rejected_by, cr.rejected_at && formatFullDate(cr.rejected_at)])}
    </p>
  );
}

/** ④ Approve & run: the actual approval (or rejection / cancellation), approve / reject while the plan waits and
 *  retry while the run was not queued (the same handlers as the status line's primary, outlined: the page has one
 *  filled button), then every run's evidence, newest open. A run's failure sentence is the status line's (P3).
 *  When the change ended here (no ⑤ is drawn), the acceptance is closed here too: the system's verdict note, or
 *  who judged the latest run. */
export function ChangeRunBody({
  cr, plan, runs, quietRunId, endsHere, acceptNote, onApprove, onReject, onRetry, busy, t,
}: {
  cr: ChangeRequestDetail;
  plan: FixPlan | null;
  runs: FixExecution[];          // newest first
  quietRunId: number | null;     // the run whose error_message the status line already shows
  endsHere: boolean;             // the phase list ends at this card
  acceptNote: Note | null;
  onApprove: () => void;
  onReject: () => void;
  onRetry: () => void;
  busy: boolean;
  t: T;
}) {
  const muted = "text-muted-foreground";
  const inFlight = runs.some((ex) => IN_FLIGHT.includes(ex.status));
  const judged = endsHere && !acceptNote && runs[0]?.accepted_by ? runs[0] : null;
  return (
    <div className="space-y-5 text-sm">
      {cr.approved_by && (
        <p>
          <span className={muted}>{t("plans.approvedBy")}: </span>
          {joinDot([
            cr.approved_by,
            cr.approved_at && formatFullDate(cr.approved_at),
            plan?.approved_hash &&
              `${t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))} ${shortHash(plan.approved_hash)}`,
          ])}
          {cr.approval_reason && <span className={`block ${muted}`}>{cr.approval_reason}</span>}
        </p>
      )}
      <ClosedRecord cr={cr} t={t} />

      {cr.status === "planned" && (
        <div className="space-y-3 rounded-lg border border-border p-4">
          <p className={muted}>{t("changes.approveRunsNote")}</p>
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={onApprove} disabled={busy}
                    className="px-4 py-2 border border-emerald-600/40 text-emerald-600 dark:text-emerald-400 text-sm font-medium rounded-lg hover:bg-emerald-500/10 disabled:opacity-50 transition-colors">
              {t("workitem.primary.approveAndRun")}
            </button>
            <button onClick={onReject} disabled={busy}
                    className="px-4 py-2 border border-red-500/30 text-red-500 text-sm font-medium rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors">
              {t("issues.reject")}
            </button>
          </div>
        </div>
      )}
      {cr.status === "approved" && (
        <button onClick={onRetry} disabled={busy}
                className="px-4 py-2 border border-primary/40 text-primary text-sm font-medium rounded-lg hover:bg-primary/10 disabled:opacity-50 transition-colors">
          {t("workitem.primary.retryExecution")}
        </button>
      )}
      {cr.status === "executing" && !inFlight && <Spinner label={t("changes.executingNote")} />}

      {runs.length > 0 && <RunList runs={runs} quietRunId={quietRunId} t={t} />}
      {endsHere && acceptNote && <p className={muted}>{fillPlaceholders(t(acceptNote.key), acceptNote.params)}</p>}
      {judged && (
        <p>
          <span className={muted}>{t("verification.acceptedBy")}: </span>
          {joinDot([judged.accepted_by, judged.accepted_at && formatFullDate(judged.accepted_at)])}
        </p>
      )}
    </div>
  );
}
