import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useHealthIssues } from "@/hooks/useHealthIssues";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ISSUE_SCOPES } from "@/lib/issueScope";
import { issueRow } from "@/lib/workItems";
import {
  LAST_CASE_KEY, QUEUE_CAP, SEVERITY_CHOICES, SORTS, STATUS_GROUPS, capped, queueFilters, queueParams, scrollKey,
} from "@/lib/caseQueue";
import type { HealthIssue } from "@/api/types";

const session = {
  get: (k: string) => { try { return sessionStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } },
  del: (k: string) => { try { sessionStorage.removeItem(k); } catch { /* private mode */ } },
};

const SORT_KEYS: Record<(typeof SORTS)[number], string> = {
  newest: "issues.sortNewest", oldest: "issues.sortOldest", severity: "issues.sortSeverity",
};
const STATUS_KEYS: Record<(typeof STATUS_GROUPS)[number], string> = {
  all: "issues.all", active: "issues.active", resolved: "issues.resolved", dismissed: "issues.dismissed",
};

/** The Cases queue (MVP-2.7.0 S4): filters in the URL, rows are real links that keep the query. Up / Down move the
 *  focus between rows; Enter or a click selects — the focus stays in the queue. On a narrow screen the list's scroll
 *  position and the row last opened come back when you return. */
export function CaseQueue({ selectedId, wide }: { selectedId: number | null; wide: boolean }) {
  const { t } = useLocale();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const filters = queueFilters(params);
  const issues = useHealthIssues({ ...filters, account_id: useScopedAccountId() });
  const [q, setQ] = useState(filters.q ?? "");
  useEffect(() => setQ(filters.q ?? ""), [filters.q]);  // back / forward changes the URL: the box follows
  const listRef = useRef<HTMLUListElement>(null);

  const set = (key: string, value: string) => setParams(queueParams(params, key, value), { replace: true });
  const data: HealthIssue[] = issues.data ?? [];
  const rows = data.slice(0, QUEUE_CAP).map((i) => issueRow(i, location.search));
  const filtered = ["status", "severity", "q", "sort"].some((k) => params.has(k));

  // Narrow: come back to where you were — once, then the saved position is spent
  useLayoutEffect(() => {
    if (wide || !issues.data) return;
    const key = scrollKey(location.search);
    const saved = session.get(key);
    if (saved == null) return;
    session.del(key);
    window.scrollTo(0, Number(saved) || 0);
    const last = session.get(LAST_CASE_KEY);
    listRef.current?.querySelector<HTMLElement>(`[data-case-id="${last}"]`)?.focus({ preventScroll: true });
  }, [wide, issues.data, location.search]);

  // Wide: keep the selected row in view inside the queue's own scroll
  useEffect(() => {
    if (!wide || selectedId == null) return;
    listRef.current?.querySelector<HTMLElement>(`[data-case-id="${selectedId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [wide, selectedId, issues.data]);

  const remember = (id: number) => {
    session.set(LAST_CASE_KEY, String(id));
    if (!wide) session.set(scrollKey(location.search), String(window.scrollY));
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLUListElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const links = [...(listRef.current?.querySelectorAll<HTMLElement>("a[data-case-id]") ?? [])];
    if (!links.length) return;
    e.preventDefault();
    const at = links.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "Home" ? 0 : e.key === "End" ? links.length - 1
      : e.key === "ArrowDown" ? Math.min(links.length - 1, at + 1) : Math.max(0, at < 0 ? 0 : at - 1);
    links[next]?.focus();
  };

  const select = "min-w-0 rounded-md border border-border bg-card px-1.5 py-1 text-xs text-foreground";
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold text-foreground">{t("issues.title")}</h1>
        <Link to="/app/signals" className="text-xs text-primary hover:underline">{t("workitem.rawSignals")}</Link>
      </div>

      <div className="space-y-2">
        <div role="group" aria-label={t("workitem.filter.scope")} className="flex rounded-md border border-border p-0.5">
          {ISSUE_SCOPES.map((s) => (
            <button key={s} type="button" aria-pressed={filters.scope === s} onClick={() => set("scope", s)}
                    className={`flex-1 rounded px-2 py-1 text-xs ${filters.scope === s
                      ? "bg-selected font-semibold text-primary" : "text-muted-foreground hover:text-foreground"}`}>
              {t(`issues.scope.${s}`)}
            </button>
          ))}
        </div>
        <input type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") set("q", q.trim()); }} onBlur={() => set("q", q.trim())}
               placeholder={t("cases.searchPlaceholder")} aria-label={t("issues.search")}
               className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm placeholder:text-muted-foreground" />
        <div className="grid grid-cols-3 gap-1.5">
          <select aria-label={t("workitem.filter.status")} className={select} value={params.get("status") ?? "all"}
                  onChange={(e) => set("status", e.target.value)}>
            {STATUS_GROUPS.map((g) => <option key={g} value={g}>{t(STATUS_KEYS[g])}</option>)}
          </select>
          <select aria-label={t("workitem.filter.severity")} className={select} value={filters.severity ?? ""}
                  onChange={(e) => set("severity", e.target.value)}>
            <option value="">{t("cases.allSeverities")}</option>
            {SEVERITY_CHOICES.map((s) => <option key={s} value={s}>{t(`severity.${s}`)}</option>)}
          </select>
          <select aria-label={t("cases.sort")} className={select} value={filters.sort}
                  onChange={(e) => set("sort", e.target.value)}>
            {SORTS.map((s) => <option key={s} value={s}>{t(SORT_KEYS[s])}</option>)}
          </select>
        </div>
      </div>

      {issues.error && <ErrorBanner message={issues.error.message} onRetry={() => issues.refetch()} actionLabel={t("common.retry")} />}
      {capped(data) && <p className="text-xs text-amber-600 dark:text-amber-400">{t("cases.capped").replace("{n}", String(QUEUE_CAP))}</p>}

      <nav aria-label={t("cases.queue")} className={wide ? "min-h-0 flex-1 overflow-y-auto pr-1" : ""}>
        {issues.isLoading ? <Spinner label={t("common.loading")} />
          : rows.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              <p>{t("cases.empty")}</p>
              {filtered && (
                <button type="button" className="mt-2 text-primary hover:underline"
                        onClick={() => { setQ(""); setParams(params.get("scope") ? { scope: params.get("scope")! } : {}, { replace: true }); }}>
                  {t("cases.clear")}
                </button>
              )}
            </div>
          ) : (
            <ul ref={listRef} onKeyDown={onKeyDown} className="space-y-1.5">
              {rows.map((r, i) => {
                const id = data[i].id;
                const current = id === selectedId;
                return (
                  <li key={r.key}>
                    <Link to={r.href} state={{ fromQueue: true }} data-case-id={id} onClick={() => remember(id)}
                          aria-current={current ? "page" : undefined}
                          className={`block rounded-md border px-3 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/60 ${
                            current ? "border-primary/50 bg-selected" : "border-border bg-card hover:bg-accent"} ${
                            r.emphasis === "closed" ? "opacity-70" : ""}`}>
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs text-muted-foreground">{r.ref}</span>
                        <SeverityBadge severity={data[i].severity} />
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-sm font-medium text-foreground">{r.title}</span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={r.subtitleFull ?? undefined}>
                        {[r.subtitle, t(r.statusKey)].filter(Boolean).join(" · ")}
                        {r.recurrence > 1 && ` · ×${r.recurrence}`}
                      </span>
                      {r.waitKey && <span className="mt-0.5 block text-xs text-primary">{t(r.waitKey)}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
      </nav>
    </div>
  );
}
