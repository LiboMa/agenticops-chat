import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import { PAGE_SIZES, healthKey, lifecycleKey, resourceFilters, resourceHref, resourceParams } from "@/lib/resourceTable";

const HEALTH_STYLE: Record<string, string> = {
  unknown: "bg-secondary text-muted-foreground",
  notice: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  warning: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  critical: "bg-red-500/10 text-red-600 dark:text-red-400",
};

/** Resources (MVP-2.7.0 S4): filters and page in the URL, the account from the top bar's scope; each row is a real
 *  link. The server orders the rows (type, then id), so paging never repeats or skips one — and there is no header
 *  sort, which could only have sorted the page on screen. */
export default function Resources() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const f = resourceFilters(params);
  const accountId = useScopedAccountId();
  const accounts = useAccounts();
  const typeCounts = useResourceTypeCounts(f.includeAbsent);
  const { data, isLoading, error, refetch } = useResources({ ...f, account_id: accountId });
  const [q, setQ] = useState(f.search ?? "");
  useEffect(() => setQ(f.search ?? ""), [f.search]);  // back / forward changes the URL: the box follows
  // a new account scope is a new list: start it at page 1
  const [lastScope, setLastScope] = useState(accountId);
  useEffect(() => {
    if (lastScope === accountId) return;
    setLastScope(accountId);
    if (params.has("page")) setParams(resourceParams(params, "page", "1"), { replace: true });
  }, [accountId, lastScope, params, setParams]);

  const set = (key: string, value: string) => setParams(resourceParams(params, key, value), { replace: true });
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil(total / f.size));
  const { types, regions, accountNames } = useMemo(() => {
    const regionSet = new Set<string>();
    for (const a of accounts.data ?? []) for (const r of a.regions ?? []) regionSet.add(r);
    return {
      types: typeCounts.data ? Object.keys(typeCounts.data).sort() : [],
      regions: [...regionSet].sort(),
      accountNames: new Map((accounts.data ?? []).map((a) => [a.id, a.name])),
    };
  }, [typeCounts.data, accounts.data]);

  const select = "rounded-md border border-border bg-card px-2.5 py-1.5 text-sm";
  const th = "px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground";
  const pageBtn = "rounded-md border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-30";
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-semibold text-foreground">{t("resources.title")}</h1>
        <span className="text-sm text-muted-foreground">{total}</span>
      </div>
      {error && <ErrorBanner message={error.message} onRetry={() => refetch()} actionLabel={t("common.retry")} />}

      <div className="flex flex-wrap items-center gap-2">
        <input type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") set("q", q.trim()); }} onBlur={() => set("q", q.trim())}
               placeholder={t("resources.search")} aria-label={t("resources.search")}
               className="w-64 rounded-md border border-border bg-card px-3 py-1.5 text-sm placeholder:text-muted-foreground" />
        <select aria-label={t("resources.col.type")} className={select} value={f.type ?? ""} onChange={(e) => set("type", e.target.value)}>
          <option value="">{t("resources.allTypes")}</option>
          {types.map((tp) => <option key={tp} value={tp}>{tp}</option>)}
        </select>
        <select aria-label={t("resources.col.region")} className={select} value={f.region ?? ""} onChange={(e) => set("region", e.target.value)}>
          <option value="">{t("resources.allRegions")}</option>
          {regions.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <input type="checkbox" checked={f.includeAbsent} onChange={(e) => set("absent", e.target.checked ? "1" : "")} className="rounded border-border" />
          {t("resources.showAbsent")}
        </label>
      </div>

      {isLoading ? <Spinner label={t("common.loading")} /> : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr className="border-b border-border">
                {["name", "type", "account", "region", "lifecycle", "health", "observed"].map((c) => (
                  <th key={c} scope="col" className={th}>{t(`resources.col.${c}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-muted-foreground">{t("dashboard.noResources")}</td></tr>
              ) : items.map((r) => {
                const absent = !!r.absent_since;
                const health = r.health ?? "unknown";
                return (
                  // the name's link stretches over the row: a click anywhere opens it, a middle click opens a tab
                  <tr key={r.id} className="relative border-b border-border/60 last:border-b-0 hover:bg-accent">
                    <td className="max-w-[320px] px-4 py-2.5">
                      <Link to={resourceHref(r.id)} className="block truncate text-sm font-medium text-foreground after:absolute after:inset-0 hover:text-primary">
                        {r.resource_name || r.resource_id}
                      </Link>
                      <span className={`block truncate font-mono text-xs text-muted-foreground ${absent ? "line-through opacity-60" : ""}`} title={r.resource_id}>
                        {r.resource_id}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-sm">{r.resource_type}</td>
                    <td className="px-4 py-2.5 text-sm text-muted-foreground">{accountNames.get(r.account_id) ?? "—"}</td>
                    <td className="px-4 py-2.5 text-sm text-muted-foreground">{r.region}</td>
                    <td className="px-4 py-2.5 text-xs">
                      <span className={absent ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}
                            title={absent ? `${t("resources.absent")} · ${formatShortDate(r.absent_since)}` : undefined}>
                        {t(lifecycleKey(r))}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      <span className={`rounded px-1.5 py-0.5 ${HEALTH_STYLE[health] ?? HEALTH_STYLE.unknown}`}>{t(healthKey(health))}</span>
                      {(r.open_issues ?? 0) > 0 && (
                        <span className="ml-1.5 text-muted-foreground">{t("resources.openIssues").replace("{n}", String(r.open_issues))}</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">{formatShortDate(r.scanned_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-sm">
              <label className="flex items-center gap-2 text-muted-foreground">
                {t("resources.rowsPerPage")}
                <select value={f.size} onChange={(e) => set("size", e.target.value)} className="rounded-md border border-border bg-background px-2 py-1 text-sm">
                  {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground">
                  {t("resources.range").replace("{from}", String(f.offset + 1))
                    .replace("{to}", String(Math.min(f.offset + f.size, total))).replace("{total}", String(total))}
                </span>
                <div className="flex gap-1">
                  <button type="button" aria-label={t("resources.firstPage")} className={pageBtn} disabled={f.page <= 1} onClick={() => set("page", "1")}>&laquo;</button>
                  <button type="button" aria-label={t("resources.prevPage")} className={pageBtn} disabled={f.page <= 1} onClick={() => set("page", String(f.page - 1))}>&lsaquo;</button>
                  <span className="px-2 py-1 font-mono text-xs">{f.page} / {pages}</span>
                  <button type="button" aria-label={t("resources.nextPage")} className={pageBtn} disabled={f.page >= pages} onClick={() => set("page", String(f.page + 1))}>&rsaquo;</button>
                  <button type="button" aria-label={t("resources.lastPage")} className={pageBtn} disabled={f.page >= pages} onClick={() => set("page", String(pages))}>&raquo;</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
