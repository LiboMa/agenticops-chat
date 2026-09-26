import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useChanges } from "@/hooks/useChanges";
import { useAccounts } from "@/hooks/useAccounts";
import { useLocale } from "@/i18n/LocaleContext";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { ChangeStepper } from "@/components/plans/ChangeStepper";
import { PeriodButtons } from "@/components/plans/PeriodButtons";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import { CHANGE_STATUSES, type Period } from "@/lib/plans";
import type { ChangeRequest, ChangeStatus } from "@/api/types";

const LIST_LIMIT = 200;
const selectClass = "border border-border bg-background text-sm rounded-lg px-3 py-1.5";

export function ChangePlansTab() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"" | ChangeStatus>("");
  const [account, setAccount] = useState("");
  const [requester, setRequester] = useState("");
  // Default: all periods (M22) — an open change older than 30 days must not vanish from the list.
  const [period, setPeriod] = useState<Period | undefined>(undefined);
  const changes = useChanges({
    status: status || undefined,
    account_id: account ? Number(account) : undefined,
    period,
    limit: LIST_LIMIT,
  });
  const accounts = useAccounts();

  // Requester filter is client-side over the loaded page: exact actor keys cannot be typed.
  const requesters = useMemo(() => {
    const set = new Set((changes.data ?? []).map((c) => c.requested_by));
    if (requester) set.add(requester); // keep the selection visible even if it left the current page
    return [...set].sort();
  }, [changes.data, requester]);
  const rows = requester ? (changes.data ?? []).filter((c) => c.requested_by === requester) : (changes.data ?? []);

  const columns: Column<ChangeRequest>[] = [
    { key: "id", header: "C#", render: (c) => <span className="font-mono text-xs text-primary">C#{c.id}</span>, sortable: true, sortValue: (c) => c.id },
    { key: "title", header: t("plans.planTitle"), render: (c) => <span className="text-sm text-foreground">{c.title}</span> },
    { key: "status", header: t("plans.status"), render: (c) => <ChangeStepper cr={c} compact />, sortable: true, sortValue: (c) => c.status },
    { key: "risk", header: t("plans.risk"), render: (c) => c.risk_level ? <RiskLevelBadge level={c.risk_level} /> : <span className="text-xs text-muted-foreground">-</span> },
    { key: "type", header: t("plans.type"), render: (c) => <span className="text-xs">{t(`plans.changeType.${c.effective_change_type ?? c.requested_change_type}`)}</span> },
    { key: "by", header: t("plans.requestedBy"), render: (c) => <span className="text-xs font-mono text-muted-foreground">{c.requested_by}</span> },
    { key: "updated", header: t("plans.updated"), render: (c) => <span className="text-xs text-muted-foreground">{formatShortDate(c.updated_at ?? c.created_at)}</span>, sortable: true, sortValue: (c) => c.updated_at ?? c.created_at ?? "" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <select value={status} onChange={(e) => setStatus(e.target.value as "" | ChangeStatus)} className={selectClass}>
          <option value="">{t("plans.allStatuses")}</option>
          {CHANGE_STATUSES.map((s) => <option key={s} value={s}>{t(`changes.status.${s}`)}</option>)}
        </select>
        <select value={account} onChange={(e) => setAccount(e.target.value)} className={selectClass}>
          <option value="">{t("plans.allAccounts")}</option>
          {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} ({a.provider})</option>)}
        </select>
        <select value={requester} onChange={(e) => setRequester(e.target.value)} className={selectClass}>
          <option value="">{t("plans.allRequesters")}</option>
          {requesters.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <PeriodButtons value={period} onChange={setPeriod} allowAll />
      </div>
      {changes.isLoading ? (
        <Spinner label={t("common.loading")} />
      ) : changes.error ? (
        <ErrorBanner message={(changes.error as Error).message} onRetry={() => changes.refetch()} actionLabel={t("common.retry")} />
      ) : (
        <>
          <DataTable columns={columns} data={rows} rowKey={(c) => c.id} onRowClick={(c) => navigate(`/app/changes/${c.id}`)} emptyMessage={t("plans.noChanges")} />
          {(changes.data?.length ?? 0) >= LIST_LIMIT && (
            <p className="text-xs text-muted-foreground">{t("plans.limitNote").replace("{n}", String(LIST_LIMIT))}</p>
          )}
        </>
      )}
    </div>
  );
}
