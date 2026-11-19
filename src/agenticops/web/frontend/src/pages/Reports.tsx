import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useReportsList } from "@/hooks/useReports";
import { useLocale } from "@/i18n/LocaleContext";
import { languageBadges, type PaperState } from "@/lib/reportView";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Report } from "@/api/types";
import { formatUtcDay, formatUtcTime, utcDayKey } from "@/lib/formatDate";
import { queryView } from "@/lib/queryState";
import { REPORTS_PAGE, countsView, isFiltered, reportsQuery, reportsSearch, type ReportsQuery } from "@/lib/reports";
import { StaleNotice } from "@/components/ui/QueryState";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700",
  incident: "bg-red-100 text-red-700",
  inventory: "bg-emerald-100 text-emerald-700",
  weekly: "bg-purple-100 text-purple-700",
  conversation: "bg-violet-100 text-violet-700",
  anomaly: "bg-orange-100 text-orange-700",
  newsletter: "bg-amber-100 text-amber-700",
  "security-review": "bg-rose-100 text-rose-700",
};

/** Strip markdown noise (headings/emphasis/tables/rules) so raw report bodies read as prose. */
export function plainSummary(s: string): string {
  return s
    .replace(/^#+\s*/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^\s*[-|=]{3,}\s*$/gm, " ")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 220);
}

/** Group reports by UTC calendar day (`utcDayKey`, MVP-2.8.0 S1), newest day first; rows within a day newest first. */
export function groupByDay(reports: Report[]): { day: string; rows: Report[] }[] {
  const groups = new Map<string, Report[]>();
  const sorted = [...reports].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  for (const r of sorted) {
    const day = utcDayKey(r.created_at);
    const bucket = groups.get(day);
    if (bucket) bucket.push(r);
    else groups.set(day, [r]);
  }
  return [...groups.entries()].map(([day, rows]) => ({ day, rows }));
}

const BADGE: Record<PaperState, string> = {
  ready: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  preparing: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  failed: "bg-red-500/10 text-red-700 dark:text-red-400",
  notPrepared: "bg-secondary text-muted-foreground",
  stale: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
};

/** Reports (MVP-2.9.0 N21 — the 2.8.0 spec's S4): the search, the dates and both counts are the server's, over
 *  every report the reader may see — not over the page that happens to be loaded. The query lives in the address;
 *  the search box stays in place while a new answer loads. */
export default function Reports() {
  const { t, locale } = useLocale();
  const [params, setParams] = useSearchParams();
  const query = reportsQuery(params);
  const apply = (next: ReportsQuery) => setParams(reportsSearch(params, next), { replace: true });
  const [draft, setDraft] = useState(query.q);
  // typing → the address, once the typing pauses; the address → the box, when it changed some other way (back / forward)
  useEffect(() => {
    if (draft.trim() === query.q) return;
    const id = window.setTimeout(() => apply({ ...query, q: draft }), 300);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);
  useEffect(() => setDraft((d) => (d.trim() === query.q ? d : query.q)), [query.q]);

  const list = useReportsList(query);
  const { refetch } = list;
  const pages = list.data?.pages ?? [];
  const loaded = useMemo(() => pages.flatMap((p) => p.items), [pages]);
  const last = pages[pages.length - 1];
  const listView = queryView(list, () => false);
  const groups = useMemo(() => groupByDay(loaded), [loaded]);
  const counts = last ? countsView(query, last.total, last.all_total) : null;
  const remaining = last ? last.total - loaded.length : 0;
  const filtered = isFiltered(query);
  const field = "h-9 rounded-lg border border-border bg-background px-3 text-[16px] sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500";

  return (
    <div className="space-y-6">
      {listView.stale && <StaleNotice asOf={listView.asOf} onRetry={() => void refetch()} />}
      <Card>
        <CardHeader className="flex-wrap gap-3">
          <div>
            <h2 className="text-lg font-semibold text-foreground">{t("reports.title")}</h2>
            <p className="text-xs text-muted-foreground">{t("reports.intro")}</p>
          </div>
          <div className="flex min-w-0 flex-1 basis-80 flex-col items-stretch gap-1.5 sm:items-end">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <input
                type="search"
                aria-label={t("reports.search")}
                placeholder={t("reports.search")}
                maxLength={200}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className={`${field} min-w-0 flex-1 basis-56 sm:w-64 sm:flex-none`}
              />
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {t("reports.from")}
                <input type="date" aria-label={`${t("reports.from")} (${t("reports.dateHint")})`} value={query.from} max={query.to || undefined}
                       onChange={(e) => apply({ ...query, q: draft, from: e.target.value })} className={`${field} px-2`} />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {t("reports.to")}
                <input type="date" aria-label={`${t("reports.to")} (${t("reports.dateHint")})`} value={query.to} min={query.from || undefined}
                       onChange={(e) => apply({ ...query, q: draft, to: e.target.value })} className={`${field} px-2`} />
              </label>
              {filtered && (
                <button type="button" onClick={() => { setDraft(""); apply({ q: "", from: "", to: "" }); }}
                        className="h-9 rounded-lg border border-border px-3 text-xs hover:bg-accent">{t("reports.clear")}</button>
              )}
            </div>
            <p className="text-xs text-muted-foreground" role="status">
              {counts && counts.matched !== null && <><span className="font-medium text-foreground">{t("reports.matched").replace("{n}", String(counts.matched))}</span>{" · "}</>}
              {counts && <span>{t("reports.all").replace("{n}", String(counts.all))}</span>}
              {counts && " · "}{t("reports.searchScope")} · {t("reports.dateHint")}
            </p>
          </div>
        </CardHeader>
        <CardBody className="p-0">
          {listView.kind === "loading" ? (
            <div className="py-12"><Spinner label={t("common.loading")} /></div>
          ) : listView.kind === "error" ? (
            <div className="p-5">
              <ErrorBanner message={`${t("common.state.failed")} · ${list.error?.message ?? ""}`} onRetry={() => void refetch()} actionLabel={t("common.retry")} />
            </div>
          ) : groups.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground text-sm">
              {filtered ? t("reports.empty.filtered") : t("reports.empty")}
            </div>
          ) : (
            <div className={list.isPlaceholderData ? "opacity-60" : ""}>
              {groups.map(({ day, rows }) => (
                <div key={day}>
                  <div className="px-5 py-1.5 bg-muted/50 border-y border-border/50 text-[11px] font-medium text-muted-foreground uppercase tracking-[0.08em] sticky top-0">
                    {formatUtcDay(day, locale)}
                    <span className="ml-2 normal-case tracking-normal text-muted-foreground/60">{rows.length}</span>
                  </div>
                  {rows.map((r) => (
                    <Link
                      key={r.id}
                      to={`/app/reports/${r.id}`}
                      className="flex items-start gap-4 px-5 py-3 border-b border-border/50 transition-colors hover:bg-accent"
                    >
                      <Badge
                        className={`mt-0.5 flex-shrink-0 ${TYPE_COLORS[r.report_type] ?? "bg-secondary text-muted-foreground"}`}
                      >
                        {r.report_type}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-sm font-medium text-foreground line-clamp-1">{r.title}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">R#{r.id} · v{r.content_version ?? 1}</span>
                          {r.visibility === "private" && (
                            <span className="rounded px-1.5 py-0.5 text-[10px] bg-secondary text-muted-foreground">{t("reports.private")}</span>
                          )}
                          {languageBadges(r).map((b) => (
                            <span key={b.lang} className={`rounded px-1.5 py-0.5 text-[10px] ${BADGE[b.state]}`}
                                  title={t(`reports.state.${b.state}`)}>
                              {b.lang === "zh" ? "中" : "EN"} · {t(`reports.state.${b.state}`)}
                            </span>
                          ))}
                        </div>
                        <div className="text-sm text-muted-foreground line-clamp-2 mt-0.5">
                          {plainSummary(r.summary)}
                        </div>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap mt-1">
                        {formatUtcTime(r.created_at)}
                      </span>
                    </Link>
                  ))}
                </div>
              ))}
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-xs text-muted-foreground">
                <span>{t("reports.listed").replace("{n}", String(loaded.length))}</span>
                {list.isFetchNextPageError && <span className="text-status-danger">{t("reports.more.failed")}</span>}
                {remaining > 0 && (
                  <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}
                          className="min-h-[44px] rounded-lg border border-border px-3 text-sm text-foreground hover:bg-accent disabled:opacity-60 sm:min-h-9">
                    {list.isFetchingNextPage ? t("reports.more.busy") : t("reports.more").replace("{n}", String(Math.min(REPORTS_PAGE, remaining)))}
                  </button>
                )}
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
