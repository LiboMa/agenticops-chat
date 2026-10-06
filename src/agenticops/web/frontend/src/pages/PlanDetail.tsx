import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useApproveFixPlan, useExecuteFixPlan, useFixPlan, useRejectFixPlan } from "@/hooks/useFixPlans";
import { useFixExecutions } from "@/hooks/useFixExecutions";
import { useEntityAudit } from "@/hooks/useEntityAudit";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/api/client";
import { PlanView } from "@/components/plans/PlanView";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { RunList } from "@/components/workitem/RunList";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { RiskLevel } from "@/api/types";
import { approvalCopy } from "@/lib/approval";
import { planDetailModel } from "@/lib/planDetailModel";
import { planLabel, shortHash } from "@/lib/plans";
import { newestFirst } from "@/lib/issueDetail";
import { formatFullDate } from "@/lib/formatDate";

/** /app/plans/:id — a fix plan as an approver reads it (MVP-2.7.0 S3): where it comes from, what it changes and how
 *  it is checked, then the approval and its runs. A change plan lives on its change request. */
export default function PlanDetail() {
  const { t } = useLocale();
  const id = Number(useParams().id);
  const q = useFixPlan(id);
  const runs = useFixExecutions(id);
  const audit = useEntityAudit("fix_plan", id);
  const approveMut = useApproveFixPlan();
  const rejectMut = useRejectFixPlan();
  const executeMut = useExecuteFixPlan();
  const { confirm, dialog } = useConfirm();
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const back = <Link to="/app/plans" className="text-sm text-muted-foreground hover:text-foreground">← {t("nav.plans")}</Link>;

  if (!Number.isInteger(id) || id <= 0 || (q.error instanceof ApiError && q.error.status === 404)) {
    return <div className="mx-auto max-w-[960px] space-y-3">{back}<p className="text-sm text-muted-foreground">{t("plans.detail.notFound")}</p></div>;
  }
  if (q.isLoading) return <Spinner label={t("common.loading")} />;
  if (q.error || !q.data) return <ErrorBanner message={q.error?.message ?? ""} onRetry={() => q.refetch()} actionLabel={t("common.retry")} />;

  const plan = q.data;
  const m = planDetailModel(plan, runs.data);
  if (m.redirect) return <Navigate to={m.redirect} replace />;
  const copy = approvalCopy(m.actions.approve?.effect);
  const label = planLabel(plan, t);
  const approvedReason = audit.data?.find((r) => r.action === "plan.approved")?.details?.reason;
  const onExecute = async () => {
    if (await confirm(t("plans.executeConfirm"), { confirmText: t("issues.execute"), cancelText: t("common.cancel") })) executeMut.mutate(plan.id);
  };
  const btn = "rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50";

  return (
    <div className="mx-auto max-w-[960px] space-y-5">
      {back}
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono">{label}</span>
          <RiskLevelBadge level={plan.risk_level as RiskLevel} />
          <FixPlanStatusBadge status={plan.status} />
          <span className="rounded bg-secondary px-1.5 py-0.5">{t(m.runKey)}</span>
        </div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold text-foreground">{plan.title}</h1>
          <div className="flex gap-2">
            {m.actions.approve && <button className={`${btn} bg-primary text-primary-foreground hover:bg-primary-hover`} disabled={approveMut.isPending} onClick={() => { approveMut.reset(); setOpen("approve"); }}>{t(copy.buttonKey)}</button>}
            {m.actions.reject && <button className={`${btn} border border-red-500/40 text-red-600`} disabled={rejectMut.isPending} onClick={() => { rejectMut.reset(); setOpen("reject"); }}>{t("issues.reject")}</button>}
            {m.actions.execute && <button className={`${btn} bg-primary text-primary-foreground hover:bg-primary-hover`} disabled={executeMut.isPending} onClick={onExecute}>{t("issues.execute")}</button>}
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          {plan.health_issue_id != null && <>{t("plans.detail.origin")}: <Link className="text-primary hover:underline" to={`/app/issues/${plan.health_issue_id}`}>I#{plan.health_issue_id} {plan.issue_title}</Link></>}
          {plan.target?.resource_id && <> · {t("plans.detail.target")}: {m.targetLink ? <Link className="text-primary hover:underline" to={m.targetLink}>{plan.target.resource_id}</Link> : <span className="font-mono">{plan.target.resource_id}</span>}</>}
          {plan.target?.region && <> · {plan.target.region}</>}
          {" · "}{t("plans.hash")} {shortHash(plan.content_hash)}
        </p>
        {executeMut.error && <p role="alert" className="text-sm text-red-500">{executeMut.error.message}</p>}
      </header>

      <PlanView plan={plan} t={t} />

      <section className="space-y-2 rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">{t("plans.detail.approval")}</h2>
        {plan.approved_by ? (
          <p className="text-sm text-muted-foreground">
            {t("issues.approvedBy")}: <span className="text-foreground">{plan.approved_by}</span>
            {plan.approved_at && <> · {formatFullDate(plan.approved_at)}</>}
            {" · "}{t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))} {shortHash(plan.approved_hash)}
            {typeof approvedReason === "string" && approvedReason && <span className="block text-foreground">{approvedReason}</span>}
          </p>
        ) : plan.rejected_by ? (
          <p className="text-sm text-muted-foreground">{t("plans.detail.rejectedBy")}: <span className="text-foreground">{plan.rejected_by}</span>{plan.rejection_reason && <span className="block text-foreground">{plan.rejection_reason}</span>}</p>
        ) : <p className="text-sm text-muted-foreground">{t("plans.detail.noApproval")}</p>}
      </section>

      <section className="space-y-2 rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">{t("plans.detail.runs")}</h2>
        {runs.isLoading ? <Spinner label={t("common.loading")} />
          : runs.error ? <ErrorBanner message={runs.error.message} onRetry={() => runs.refetch()} actionLabel={t("common.retry")} />
          : (runs.data?.length ?? 0) === 0 ? <p className="text-sm text-muted-foreground">{t("plans.detail.noRuns")}</p>
          : <RunList runs={newestFirst(runs.data)} quietRunId={null} t={t} />}
      </section>

      <p className="text-xs text-muted-foreground">{t("plans.detail.bindNote")}</p>

      {open && (
        <ReasonDialog
          title={open === "approve" ? t(copy.titleKey).replace("{label}", label) : `${t("plans.rejectTitle")} ${label}`}
          description={open === "approve" ? `${t(copy.noteKey)} ${t("plans.hash")} ${shortHash(plan.content_hash)}` : plan.title}
          confirmText={open === "approve" ? t(copy.buttonKey) : t("issues.reject")}
          variant={open === "reject" ? "destructive" : "default"}
          required={open === "reject"}
          ack={open === "approve" ? t("approval.ack") : undefined}
          busy={approveMut.isPending || rejectMut.isPending}
          error={(open === "approve" ? approveMut.error : rejectMut.error)?.message ?? null}
          onConfirm={(reason) => {
            const done = { onSuccess: () => setOpen(null) };
            if (open === "approve") approveMut.mutate({ id: plan.id, content_hash: plan.content_hash ?? "", reason: reason || undefined }, done);
            else rejectMut.mutate({ id: plan.id, reason }, done);
          }}
          onClose={() => setOpen(null)}
        />
      )}
      {dialog}
    </div>
  );
}
