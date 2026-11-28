import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useSchedules } from "@/hooks/useSchedules";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { StaleNotice } from "@/components/ui/QueryState";
import { StatusText } from "@/components/ui/StatusText";
import { CopyId } from "@/components/ui/CopyId";
import { formatShortDate } from "@/lib/formatDate";
import { queryView } from "@/lib/queryState";
import { shortId } from "@/lib/workItems";
import { PAGE_SIZES, healthView, lifecycleKey, resourceFilters, resourceHref, resourceParams, scanLine } from "@/lib/resourceTable";
import type { PaginatedResources, Resource } from "@/api/types";

import { fillPlaceholders } from "@/lib/placeholders";
type T = (key: string) => string;

/** A row's health in words (MVP-2.9.0 N24): an open issue's level and count, else why there is none to report —
 *  «no known issue», «data out of date · last observed 2 days ago», «never observed», «gone». Never «healthy». */
function Health({ r, t }: { r: Resource; t: T }) {
  const view = healthView(r);
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 text-xs">
      <StatusText tone={view.tone} className="whitespace-normal">{t(view.key)}</StatusText>
      {view.issues > 0 && <span className="text-muted-foreground">{fillPlaceholders(t("resources.openIssues"), { n: String(view.issues) })}</span>}
      {view.ago && (
        <span className="text-muted-foreground">
          · {fillPlaceholders(t("resources.lastObserved"), { ago: fillPlaceholders(t(view.ago.key), { n: String(view.ago.n) }) })}
        </span>
      )}
    </span>
  );
}

/** Resources (MVP-2.7.0 S4): filters and page in the URL, the account from the top bar's scope; each row is a real
 *  link. The server orders the rows (type, then id), so paging never repeats or skips one — and there is no header
 *  sort, which could only have sorted the page on screen. MVP-2.9.0 N24 (the 2.8.0 spec's S7): every row says WHY its
 *  health reads as it does and shows a short id with a copy button; below 768 px the table is a list of cards; the
 *  header says when resources were last scanned. */
export default function Resources() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const f = resourceFilters(params);
  const accountId = useScopedAccountId();
  const accounts = useAccounts();
  const schedules = useSchedules();
  const typeCounts = useResourceTypeCounts(f.includeAbsent);
  const list = useResources({ ...f, account_id: accountId }, true, true);
  const { data, refetch } = list;
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
  const view = queryView<PaginatedResources>(list, (d) => d.items.length === 0);
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil(total / f.size));
  const scan = scanLine(schedules.data);
  const { types, regions, accountNames } = useMemo(() => {
    const regionSet = new Set<string>();
    for (const a of accounts.data ?? []) for (const r of a.regions ?? []) regionSet.add(r);
    return {
      types: typeCounts.data ? Object.keys(typeCounts.data).sort() : [],
      regions: [...regionSet].sort(),
      accountNames: new Map((accounts.data ?? []).map((a) => [a.id, a.name])),
    };
  }, [typeCounts.data, accounts.data]);

  const select = "rounded-md border border-border bg-card px-2.5 py-1.5 text-[16px] sm:text-sm";
  const th = "px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground";
  const pageBtn = "rounded-md border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-30 max-[767px]:min-h-[44px] max-[767px]:min-w-[44px]";
  const name = (r: Resource) => r.resource_name || r.resource_id;
  const observed = (r: Resource) => r.observed_at ?? r.scanned_at;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold text-foreground">{t("resources.title")}</h1>
          {data && <span className="text-sm text-muted-foreground">{total}</span>}
        </div>
        {/* when resources were last scanned: the newest run of the resource-scan schedule, with its real state */}
        {scan && (
          <p className="mt-1 text-xs text-muted-foreground">
            {scan.scheduleId === null ? t("resources.scan.none") : (
              <>
                {t("resources.scan.label")}: <span className="text-foreground">{scan.at ? formatShortDate(scan.at) : t("schedules.run.never_run")}</span>
                {scan.at && <> · {scan.run.kind === "other" ? scan.run.raw : t(`schedules.run.${scan.run.kind}`)}</>}
                {!scan.enabled && <> · <span className="text-status-warn">{t("resources.scan.disabled")}</span></>}
                {" · "}<Link to={`/app/schedules/${scan.scheduleId}`} className="text-primary hover:underline">{t("resources.scan.history")}</Link>
              </>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") set("q", q.trim()); }} onBlur={() => set("q", q.trim())}
               placeholder={t("resources.search")} aria-label={t("resources.search")}
               className="w-full rounded-md border border-border bg-card px-3 py-1.5 text-[16px] placeholder:text-muted-foreground sm:w-64 sm:text-sm" />
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

      {view.stale && <StaleNotice asOf={view.asOf} onRetry={() => void refetch()} />}
      {view.kind === "loading" ? <Spinner label={t("common.loading")} />
        : view.kind === "error" ? (
          <ErrorBanner message={`${t("common.state.failed")}${list.error?.message ? ` · ${list.error.message}` : ""}`}
                       onRetry={() => void refetch()} actionLabel={t("common.retry")} />
        ) : (
        <div className={`rounded-lg border border-border bg-card ${list.isPlaceholderData ? "opacity-60" : ""}`}>
          {view.kind === "empty" ? (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">{t("resources.empty")}</p>
          ) : (
            <>
              {/* from 768 px: the table */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full min-w-[860px]">
                  <thead>
                    <tr className="border-b border-border">
                      {["name", "type", "account", "region", "lifecycle", "health", "observed"].map((c) => (
                        <th key={c} scope="col" className={th}>{t(`resources.col.${c}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((r) => {
                      const absent = !!r.absent_since;
                      return (
                        // the name's link stretches over the row: a click anywhere opens it, a middle click opens a tab
                        <tr key={r.id} className="relative border-b border-border/60 last:border-b-0 hover:bg-accent">
                          <td className="max-w-[320px] px-4 py-2">
                            <Link to={resourceHref(r.id)} className="block truncate text-sm font-medium text-foreground after:absolute after:inset-0 hover:text-primary">
                              {name(r)}
                            </Link>
                            <CopyId id={r.resource_id} short={shortId(r.resource_id)} struck={absent} />
                          </td>
                          <td className="px-4 py-2 text-sm">{r.resource_type}</td>
                          <td className="px-4 py-2 text-sm text-muted-foreground">{accountNames.get(r.account_id) ?? "—"}</td>
                          <td className="px-4 py-2 text-sm text-muted-foreground">{r.region}</td>
                          <td className="px-4 py-2 text-xs">
                            <span className={absent ? "text-status-warn" : "text-muted-foreground"}
                                  title={absent ? `${t("resources.absent")} · ${formatShortDate(r.absent_since)}` : undefined}>
                              {t(lifecycleKey(r))}
                            </span>
                          </td>
                          <td className="px-4 py-2"><Health r={r} t={t} /></td>
                          <td className="whitespace-nowrap px-4 py-2 text-xs text-muted-foreground">{formatShortDate(observed(r))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* below 768 px: one card per resource — health and account readable without scrolling sideways */}
              <ul className="divide-y divide-border/60 md:hidden">
                {items.map((r) => (
                  <li key={r.id} className="relative px-4 py-3">
                    <Link to={resourceHref(r.id)} className="block text-sm font-medium text-foreground [overflow-wrap:anywhere] after:absolute after:inset-0">
                      {name(r)}
                    </Link>
                    <CopyId id={r.resource_id} short={shortId(r.resource_id)} struck={!!r.absent_since} />
                    <div className="mt-1"><Health r={r} t={t} /></div>
                    <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
                      <dt className="text-muted-foreground">{t("resources.col.type")}</dt><dd className="[overflow-wrap:anywhere]">{r.resource_type}</dd>
                      <dt className="text-muted-foreground">{t("resources.col.account")}</dt><dd className="[overflow-wrap:anywhere]">{accountNames.get(r.account_id) ?? "—"}</dd>
                      <dt className="text-muted-foreground">{t("resources.col.region")}</dt><dd>{r.region}</dd>
                      <dt className="text-muted-foreground">{t("resources.col.observed")}</dt><dd>{formatShortDate(observed(r))}</dd>
                    </dl>
                  </li>
                ))}
              </ul>
            </>
          )}

          {total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm md:px-5">
              <label className="flex items-center gap-2 text-muted-foreground">
                {t("resources.rowsPerPage")}
                <select value={f.size} onChange={(e) => set("size", e.target.value)} className="rounded-md border border-border bg-background px-2 py-1 text-[16px] sm:text-sm">
                  {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-muted-foreground">
                  {fillPlaceholders(t("resources.range"), { from: String(f.offset + 1), to: String(Math.min(f.offset + f.size, total)), total: String(total) })}
                </span>
                <div className="flex items-center gap-1">
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
