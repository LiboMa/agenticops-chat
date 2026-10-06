import type { FixExecution, FixPlan, IssueStatus } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { RunList } from "@/components/workitem/RunList";
import { RunningFor } from "@/components/workitem/RunningFor";
import { approvalBlockedReason, canApprovePlan } from "@/lib/issueDetail";
import { formatFullDate } from "@/lib/formatDate";

type T = (key: string) => string;

/** ③ Approve & run: who approved which version, approve / reject while the plan waits (the same handlers as the
 *  status line's primary), then every run's evidence. A run's failure sentence is the status line's, not here (P3). */
export function RunBody({
  plan, issueStatus, runs, loading, error, onRetryFetch, quietRunId, autoRunSince, onApprove, onReject, approving, rejecting, approveLabel, t,
}: {
  plan: FixPlan | null;
  issueStatus: IssueStatus;
  runs: FixExecution[];          // newest first
  loading: boolean;
  error: Error | null;
  onRetryFetch: () => void;
  quietRunId: number | null;     // the run whose error_message the status line already shows
  autoRunSince: string | null;   // the approval's auto-run under way since then: it has no record until it ends
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
  rejecting: boolean;
  approveLabel: string;   // "Approve" or "Approve & run", by what approving really does (MVP-2.7.0 S3)
  t: T;
}) {
  const approvable = !!plan && canApprovePlan(plan, issueStatus);
  // a plan of a resolved / dismissed issue can still be rejected, not approved
  const blocked = plan ? approvalBlockedReason(plan, issueStatus) : null;
  return (
    <div className="space-y-5">
      {plan && (plan.approved_by || plan.approved_at) && (
        <p className="text-sm text-muted-foreground">
          {plan.approved_by && <>{t("issues.approvedBy")}: <span className="font-medium text-foreground">{plan.approved_by}</span></>}
          {plan.approved_at && <> · {t("issues.approvedAt")}: <span className="text-foreground">{formatFullDate(plan.approved_at)}</span></>}
          {" · "}{t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))}
        </p>
      )}

      {plan && (approvable || blocked) && (
        <div className="space-y-3 rounded-lg border border-border p-4">
          {approvable && (plan.risk_level === "L2" || plan.risk_level === "L3") && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-sm text-amber-500">
              <strong>{plan.risk_level} {t("issues.approvalWarning")}</strong>
            </div>
          )}
          {blocked && <p className="text-sm text-muted-foreground">{t(`issues.approvalBlocked.${blocked}`)}</p>}
          <div className="flex items-center gap-3">
            {approvable && (
              <button onClick={onApprove} disabled={approving}
                      className="px-4 py-2 border border-emerald-600/40 text-emerald-600 dark:text-emerald-400 text-sm font-medium rounded-lg hover:bg-emerald-500/10 disabled:opacity-50 transition-colors">
                {approveLabel}
              </button>
            )}
            <button onClick={onReject} disabled={rejecting}
                    className="px-4 py-2 border border-red-500/30 text-red-500 text-sm font-medium rounded-lg hover:bg-red-500/10 disabled:opacity-50 transition-colors">
              {rejecting ? t("issues.rejecting") : t("issues.reject")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <Spinner label={t("common.loading")} />
      ) : error ? (
        // a failed fetch must not read as "no executions"
        <ErrorBanner message={error.message} onRetry={onRetryFetch} actionLabel={t("common.retry")} />
      ) : autoRunSince ? (
        // the approval's own run: no record until it ends, so earlier runs (if any) follow it
        <div className="space-y-3">
          <div className="space-y-1">
            <RunningFor since={autoRunSince} t={t} />
            <p className="text-sm text-muted-foreground">{t("workitem.autoRunNote")}</p>
          </div>
          {runs.length > 0 && <RunList runs={runs} quietRunId={quietRunId} t={t} />}
        </div>
      ) : runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(plan ? "issues.noExecutions" : "workitem.future.issue.run")}</p>
      ) : (
        <RunList runs={runs} quietRunId={quietRunId} t={t} />
      )}
    </div>
  );
}
