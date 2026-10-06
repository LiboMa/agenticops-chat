import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useChanges } from "@/hooks/useChanges";
import { useAccounts } from "@/hooks/useAccounts";
import { useLocale } from "@/i18n/LocaleContext";
import { WorkItemTable } from "@/components/ui/WorkItemTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { PeriodButtons } from "@/components/plans/PeriodButtons";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { CHANGE_STATUSES, changeFilters, type Period } from "@/lib/plans";
import { changeRow } from "@/lib/workItems";
import type { ChangeStatus, RiskLevel } from "@/api/types";

const LIST_LIMIT = 200;
const selectClass = "border border-border bg-background text-sm rounded-lg px-3 py-1.5";

export function ChangePlansTab() {
  const { t } = useLocale();
  // The filters live in the URL (hub tab ?tab=changes&status=…), so a link or a refresh shows the same list.
  // Default: all periods (M22) — an open change older than 30 days must not vanish from the list.
  const [params, setParams] = useSearchParams();
  const f = changeFilters(params);
  const status = f.status ?? "";
  const account = f.account_id ? String(f.account_id) : "";
  const requester = f.requested_by ?? "";
  const period = f.period;
  const set = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const setStatus = (v: "" | ChangeStatus) => set("status", v);
  const setAccount = (v: string) => set("account_id", v);
  const setRequester = (v: string) => set("requested_by", v);
  const setPeriod = (v: Period | undefined) => set("period", v);
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

  const accountNames = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a.name])), [accounts.data]);
  const accountName = (id: number | null) => (id == null ? null : accountNames.get(id) ?? null);

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
          <WorkItemTable
            rows={rows.map((c) => changeRow(c, accountName(c.account_id)))}
            levelHeader={t("plans.risk")}
            renderLevel={(r) => (
              <span className="inline-flex items-center gap-1.5">
                {r.level ? <RiskLevelBadge level={r.level as RiskLevel} /> : <span className="text-xs text-muted-foreground">{t("workitem.unrated")}</span>}
                {r.typeKey && <span className="text-xs text-muted-foreground">{t(r.typeKey)}</span>}
              </span>
            )}
            timeHeader={t("workitem.col.updated")}
            emptyMessage={t("plans.noChanges")}
            t={t}
          />
          {(changes.data?.length ?? 0) >= LIST_LIMIT && (
            <p className="text-xs text-muted-foreground">{t("plans.limitNote").replace("{n}", String(LIST_LIMIT))}</p>
          )}
        </>
      )}
    </div>
  );
}
