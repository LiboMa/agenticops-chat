import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useFixPlans } from "@/hooks/useFixPlans";
import { useAccounts } from "@/hooks/useAccounts";
import { WorkItemTable } from "@/components/ui/WorkItemTable";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { RiskLevel } from "@/api/types";
import { PLAN_STATUS_GROUPS, fixPlanFilters } from "@/lib/plans";
import { fixPlanRow } from "@/lib/workItems";

/** The hub's Fix plans tab: every filter lives in the URL, so a link or a refresh shows the same list. */
export function FixPlansTab() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const filters = fixPlanFilters(params);
  const plans = useFixPlans({ kind: "fix", limit: 200, ...filters });
  const accounts = useAccounts();
  const [q, setQ] = useState(filters.q ?? "");
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const accountName = (id: number | null | undefined) => accounts.data?.find((a) => a.id === id)?.name ?? null;
  const filtered = !!(filters.status || filters.risk_level || filters.account_id || filters.q);
  const select = "rounded-md border border-border bg-card px-2.5 py-1.5 text-sm";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={t("plans.filter.status")} className={select} value={params.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
          <option value="">{t("plans.filter.allStatuses")}</option>
          {Object.keys(PLAN_STATUS_GROUPS).map((g) => <option key={g} value={g}>{t(`plans.group.${g}`)}</option>)}
        </select>
        <select aria-label={t("plans.risk")} className={select} value={params.get("risk") ?? ""} onChange={(e) => set("risk", e.target.value)}>
          <option value="">{t("plans.filter.allRisks")}</option>
          {["L0", "L1", "L2", "L3"].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select aria-label={t("plans.filter.account")} className={select} value={params.get("account") ?? ""} onChange={(e) => set("account", e.target.value)}>
          <option value="">{t("plans.filter.allAccounts")}</option>
          {(accounts.data ?? []).map((a) => <option key={a.id} value={String(a.id)}>{a.name}</option>)}
        </select>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100}
               onKeyDown={(e) => { if (e.key === "Enter") set("q", q.trim()); }} onBlur={() => set("q", q.trim())}
               placeholder={t("plans.filter.search")} aria-label={t("plans.filter.search")}
               className="min-w-[220px] flex-1 rounded-md border border-border bg-card px-3 py-1.5 text-sm" />
        {filtered && (
          <button type="button" className="text-sm text-primary hover:underline" onClick={() => { setQ(""); setParams({}, { replace: true }); }}>
            {t("plans.filter.clear")}
          </button>
        )}
      </div>
      {plans.isLoading ? <Spinner label={t("common.loading")} />
        : plans.error ? <ErrorBanner message={plans.error.message} onRetry={() => plans.refetch()} actionLabel={t("common.retry")} />
        : (
          <WorkItemTable
            rows={(plans.data ?? []).map((p) => fixPlanRow(p, accountName(p.account_id)))}
            levelHeader={t("plans.risk")}
            renderLevel={(r) => (r.level ? <RiskLevelBadge level={r.level as RiskLevel} /> : <span className="text-xs text-muted-foreground">{t("workitem.unrated")}</span>)}
            timeHeader={t("workitem.col.updated")}
            emptyMessage={filtered ? t("plans.fixEmptyFiltered") : t("plans.fixEmpty")}
            t={t}
          />
        )}
    </div>
  );
}
