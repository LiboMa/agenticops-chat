import { useState } from "react";
import { Link } from "react-router-dom";
import { useApproveFixPlan, useExecuteFixPlan, useFixPlans, useRejectFixPlan } from "@/hooks/useFixPlans";
import { useAccounts } from "@/hooks/useAccounts";
import { useLocale } from "@/i18n/LocaleContext";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { formatShortDate } from "@/lib/formatDate";
import { PLAN_STATUSES } from "@/lib/plans";
import type { FixPlan, FixPlanStatus, RiskLevel } from "@/api/types";

// The newest slice we render; the limit note tells the operator to narrow the filters for older rows.
const LIST_LIMIT = 200;
const RISKS: ("" | RiskLevel)[] = ["", "L0", "L1", "L2", "L3"];
const selectClass = "border border-border bg-background text-sm rounded-lg px-3 py-1.5";

export function FixPlansTab() {
  const { t } = useLocale();
  const [status, setStatus] = useState<"" | FixPlanStatus>("");
  const [risk, setRisk] = useState<"" | RiskLevel>("");
  const [account, setAccount] = useState("");
  const plans = useFixPlans({
    kind: "fix",
    status: status || undefined,
    risk_level: risk || undefined,
    account_id: account ? Number(account) : undefined,
    limit: LIST_LIMIT,
  });
  const accounts = useAccounts();
  const approve = useApproveFixPlan();
  const reject = useRejectFixPlan();
  const execute = useExecuteFixPlan();
  const { confirm, dialog } = useConfirm();
  const [pending, setPending] = useState<{ plan: FixPlan; action: "approve" | "reject" } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Reset both mutations before opening, or a previous plan's error would surface in the new dialog.
  const openReason = (plan: FixPlan, action: "approve" | "reject") => {
    approve.reset();
    reject.reset();
    setPending({ plan, action });
  };

  const onExecute = async (plan: FixPlan) => {
    if (!(await confirm(t("plans.executeConfirm"), { confirmText: t("issues.execute"), cancelText: t("common.cancel") }))) return;
    setActionError(null);
    execute.mutate(plan.id, { onError: (e) => setActionError((e as Error).message) });
  };

  const columns: Column<FixPlan>[] = [
    { key: "id", header: "#", render: (p) => <span className="font-mono text-xs">#{p.id}</span>, sortable: true, sortValue: (p) => p.id },
    { key: "issue", header: t("plans.issue"), render: (p) => p.health_issue_id ? <Link className="text-primary font-mono text-xs" to={`/app/issues/${p.health_issue_id}`}>I#{p.health_issue_id}</Link> : "-" },
    { key: "title", header: t("plans.planTitle"), render: (p) => <span className="text-sm text-foreground">{p.title}</span> },
    { key: "risk", header: t("plans.risk"), render: (p) => <RiskLevelBadge level={p.risk_level} />, sortable: true, sortValue: (p) => p.risk_level },
    { key: "status", header: t("plans.status"), render: (p) => <FixPlanStatusBadge status={p.status} />, sortable: true, sortValue: (p) => p.status },
    { key: "approved", header: t("plans.approvedBy"), render: (p) => <span className="text-xs text-muted-foreground">{p.approved_by ?? "-"}{p.approved_at ? ` · ${formatShortDate(p.approved_at)}` : ""}</span> },
    { key: "actions", header: t("plans.actions"), render: (p) => (
      <div className="flex gap-2">
        {(p.status === "draft" || p.status === "pending_approval") && (
          <>
            <button onClick={(e) => { e.stopPropagation(); openReason(p, "approve"); }} className="px-2 py-1 text-xs rounded bg-emerald-600 text-white">{t("issues.approve")}</button>
            <button onClick={(e) => { e.stopPropagation(); openReason(p, "reject"); }} className="px-2 py-1 text-xs rounded border border-red-500/40 text-red-500">{t("issues.reject")}</button>
          </>
        )}
        {p.status === "approved" && (
          <button onClick={(e) => { e.stopPropagation(); onExecute(p); }} disabled={execute.isPending}
            className="px-2 py-1 text-xs rounded bg-primary text-primary-foreground disabled:opacity-50">{t("issues.execute")}</button>
        )}
      </div>
    ) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value as "" | FixPlanStatus)} className={selectClass}>
          <option value="">{t("plans.allStatuses")}</option>
          {PLAN_STATUSES.map((s) => <option key={s} value={s}>{t(`plans.planStatus.${s}`)}</option>)}
        </select>
        <select value={risk} onChange={(e) => setRisk(e.target.value as "" | RiskLevel)} className={selectClass}>
          {RISKS.map((r) => <option key={r} value={r}>{r || t("plans.allRisks")}</option>)}
        </select>
        <select value={account} onChange={(e) => setAccount(e.target.value)} className={selectClass}>
          <option value="">{t("plans.allAccounts")}</option>
          {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.provider})</option>)}
        </select>
      </div>
      {actionError && <ErrorBanner message={actionError} onRetry={() => setActionError(null)} actionLabel={t("common.close")} />}
      {plans.isLoading ? (
        <Spinner label={t("common.loading")} />
      ) : plans.error ? (
        <ErrorBanner message={(plans.error as Error).message} onRetry={() => plans.refetch()} actionLabel={t("common.retry")} />
      ) : (
        <>
          <DataTable columns={columns} data={plans.data ?? []} rowKey={(p) => p.id} emptyMessage={t("plans.noPlans")} />
          {(plans.data?.length ?? 0) >= LIST_LIMIT && (
            <p className="text-xs text-muted-foreground">{t("plans.limitNote").replace("{n}", String(LIST_LIMIT))}</p>
          )}
        </>
      )}
      {pending && (
        <ReasonDialog
          title={`${pending.action === "approve" ? t("plans.approveTitle") : t("plans.rejectTitle")} #${pending.plan.id}`}
          description={pending.plan.title}
          confirmText={pending.action === "approve" ? t("issues.approve") : t("issues.reject")}
          variant={pending.action === "reject" ? "destructive" : "default"}
          required={pending.action === "reject"}
          busy={approve.isPending || reject.isPending}
          error={(pending.action === "approve" ? approve.error : reject.error)?.message ?? null}
          onConfirm={(reason) => {
            if (pending.action === "approve") approve.mutate({ id: pending.plan.id, content_hash: pending.plan.content_hash ?? "", reason: reason || undefined }, { onSuccess: () => setPending(null) });
            else reject.mutate({ id: pending.plan.id, reason }, { onSuccess: () => setPending(null) });
          }}
          onClose={() => setPending(null)}
        />
      )}
      {dialog}
    </div>
  );
}
