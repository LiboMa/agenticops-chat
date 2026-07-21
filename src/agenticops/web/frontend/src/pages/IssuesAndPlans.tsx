import { useState, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useLocale } from "@/i18n/LocaleContext";
import { IssueRow } from "@/components/ui/IssueRow";
import { SignalsPanel } from "@/components/signals/SignalsPanel";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Anomaly, Resource } from "@/api/types";

/* ── Issues helpers ─────────────────────────────────────────────── */

type Phase = "all" | "active" | "resolved" | "dismissed";
type Severity = "all" | "critical" | "high" | "medium" | "low";
type SortKey = "newest" | "oldest" | "severity";

// Auto-pipeline moves issues out of literal "open" within seconds, so the tab
// groups by ops semantics: Active = anything not yet closed.
const ACTIVE_STATUSES = new Set([
  "open",
  "investigating",
  "acknowledged",
  "root_cause_identified",
  "fix_planned",
  "fix_approved",
  "fix_executing",
  "fix_executed",
]);

function getPhase(status: string): Phase {
  if (ACTIVE_STATUSES.has(status)) return "active";
  if (status === "resolved") return "resolved";
  if (status === "dismissed") return "dismissed";
  return "all";
}

function matchesSearch(issue: Anomaly, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    issue.title.toLowerCase().includes(q) ||
    issue.resource_id.toLowerCase().includes(q) ||
    issue.region.toLowerCase().includes(q)
  );
}

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function sortIssues(issues: Anomaly[], key: SortKey): Anomaly[] {
  const sorted = [...issues];
  switch (key) {
    case "newest":
      return sorted.sort((a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime());
    case "oldest":
      return sorted.sort((a, b) => new Date(a.detected_at).getTime() - new Date(b.detected_at).getTime());
    case "severity":
      return sorted.sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9));
    default:
      return sorted;
  }
}

/* ── Resources helpers ──────────────────────────────────────────── */

const PAGE_SIZES = [50, 100, 200];

/* ── Main component ─────────────────────────────────────────────── */

type View = "issues" | "resources" | "signals";

export default function IssuesAndPlans() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const viewParam = searchParams.get("view");
  const view: View =
    viewParam === "resources" ? "resources" : viewParam === "signals" ? "signals" : "issues";

  function setView(v: View) {
    if (v === "issues") {
      setSearchParams({});
    } else {
      setSearchParams({ view: v });
    }
  }

  const titles: Record<View, string> = {
    issues: t("issues.title"),
    resources: t("resources.title"),
    signals: t("signals.title"),
  };

  return (
    <div className="space-y-4">
      {/* View toggle */}
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-semibold text-foreground">{titles[view]}</h1>
        <div className="flex bg-secondary rounded-lg p-0.5">
          {(["issues", "resources", "signals"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1 text-sm font-medium rounded-md transition-colors ${
                view === v
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {titles[v]}
            </button>
          ))}
        </div>
      </div>

      {view === "issues" ? (
        <IssuesView navigate={navigate} t={t} />
      ) : view === "signals" ? (
        <SignalsPanel />
      ) : (
        <ResourcesView navigate={navigate} t={t} initialType={searchParams.get("type") || ""} />
      )}
    </div>
  );
}

/* ── Issues View ────────────────────────────────────────────────── */

function IssuesView({
  navigate,
  t,
}: {
  navigate: ReturnType<typeof useNavigate>;
  t: (key: string) => string;
}) {
  const [phase, setPhase] = useState<Phase>("all");
  const [severity, setSeverity] = useState<Severity>("all");
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [search, setSearch] = useState("");
  const { data, isLoading, error, refetch } = useAnomalies();

  const allIssues = data ?? [];

  const counts = useMemo(() => {
    const c = { all: 0, active: 0, resolved: 0, dismissed: 0 };
    for (const issue of allIssues) {
      c.all++;
      const p = getPhase(issue.status);
      if (p === "active") c.active++;
      else if (p === "resolved") c.resolved++;
      else if (p === "dismissed") c.dismissed++;
    }
    return c;
  }, [allIssues]);

  const sevCounts = useMemo(() => {
    const c: Record<string, number> = { all: 0, critical: 0, high: 0, medium: 0, low: 0 };
    for (const issue of allIssues) {
      // Only count issues matching current phase filter
      if (phase !== "all" && getPhase(issue.status) !== phase) continue;
      c.all++;
      if (issue.severity in c) c[issue.severity]++;
    }
    return c;
  }, [allIssues, phase]);

  const filtered = useMemo(() => {
    const matched = allIssues.filter((issue) => {
      if (phase !== "all" && getPhase(issue.status) !== phase) return false;
      if (severity !== "all" && issue.severity !== severity) return false;
      if (!matchesSearch(issue, search)) return false;
      return true;
    });
    return sortIssues(matched, sortKey);
  }, [allIssues, phase, severity, search, sortKey]);

  const chips: { key: Phase; label: string; count: number }[] = [
    { key: "all", label: t("issues.all"), count: counts.all },
    { key: "active", label: t("issues.active"), count: counts.active },
    { key: "resolved", label: t("issues.resolved"), count: counts.resolved },
    { key: "dismissed", label: t("issues.dismissed"), count: counts.dismissed },
  ];

  return (
    <>
      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      )}

      {/* Filter bar */}
      <div className="space-y-3">
        {/* Phase chips row */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            {chips.map((chip) => (
              <button
                key={chip.key}
                onClick={() => setPhase(chip.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                  phase === chip.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent"
                }`}
              >
                {chip.label}
                <span
                  className={`inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-xs rounded-full ${
                    phase === chip.key
                      ? "bg-primary-foreground/20 text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {chip.count}
                </span>
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            {/* Sort dropdown */}
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="text-sm font-medium rounded-lg px-3 py-1.5 bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent border-none transition-colors cursor-pointer"
            >
              <option value="newest">{t("issues.sortNewest")}</option>
              <option value="oldest">{t("issues.sortOldest")}</option>
              <option value="severity">{t("issues.sortSeverity")}</option>
            </select>

            {/* Search */}
            <div className="relative">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                />
              </svg>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("issues.search")}
                className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-64"
              />
            </div>
          </div>
        </div>

        {/* Severity filter row */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground mr-1">{t("issues.severity")}:</span>
          {(["all", "critical", "high", "medium", "low"] as Severity[]).map((sev) => {
            const active = severity === sev;
            const count = sevCounts[sev] ?? 0;
            const sevColors: Record<string, string> = {
              all: active ? "bg-primary text-primary-foreground" : "",
              critical: active ? "bg-red-500/20 text-red-500 ring-1 ring-red-500/30" : "hover:bg-red-500/10 hover:text-red-500",
              high: active ? "bg-orange-500/20 text-orange-500 ring-1 ring-orange-500/30" : "hover:bg-orange-500/10 hover:text-orange-500",
              medium: active ? "bg-yellow-500/20 text-yellow-600 dark:text-yellow-400 ring-1 ring-yellow-500/30" : "hover:bg-yellow-500/10 hover:text-yellow-600 dark:hover:text-yellow-400",
              low: active ? "bg-blue-500/20 text-blue-500 ring-1 ring-blue-500/30" : "hover:bg-blue-500/10 hover:text-blue-500",
            };
            const badgeColors: Record<string, string> = {
              all: active ? "bg-primary-foreground/20 text-primary-foreground" : "bg-muted text-muted-foreground",
              critical: active ? "bg-red-500/30 text-red-500" : "bg-red-500/10 text-red-500/70",
              high: active ? "bg-orange-500/30 text-orange-500" : "bg-orange-500/10 text-orange-500/70",
              medium: active ? "bg-yellow-500/30 text-yellow-600 dark:text-yellow-400" : "bg-yellow-500/10 text-yellow-600/70 dark:text-yellow-400/70",
              low: active ? "bg-blue-500/30 text-blue-500" : "bg-blue-500/10 text-blue-500/70",
            };
            return (
              <button
                key={sev}
                onClick={() => setSeverity(sev)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                  active ? sevColors[sev] : `text-muted-foreground ${sevColors[sev]}`
                }`}
              >
                {sev === "all" ? t("issues.all") : sev}
                <span className={`inline-flex items-center justify-center min-w-[1.125rem] h-[1.125rem] px-1 text-[10px] rounded-full ${badgeColors[sev]}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Issue list */}
      {isLoading ? (
        <Spinner />
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <svg
            className="h-12 w-12 mb-3 opacity-30"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-sm">{t("issues.noIssues")}</p>
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          {filtered.map((issue) => (
            <IssueRow
              key={issue.id}
              issue={issue}
              onClick={() => navigate(`/app/issues/${issue.id}`)}
            />
          ))}
        </div>
      )}
    </>
  );
}

/* ── Resources View ─────────────────────────────────────────────── */

function ResourcesView({
  navigate,
  t,
  initialType,
}: {
  navigate: ReturnType<typeof useNavigate>;
  t: (key: string) => string;
  initialType: string;
}) {
  const [typeFilter, setTypeFilter] = useState(initialType);
  const [regionFilter, setRegionFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const accounts = useAccounts();
  const typeCounts = useResourceTypeCounts();

  const offset = (page - 1) * pageSize;

  const { data, isLoading, error, refetch } = useResources({
    type: typeFilter || undefined,
    region: regionFilter || undefined,
    account_id: accountFilter ? Number(accountFilter) : undefined,
    search: search || undefined,
    limit: pageSize,
    offset,
  });

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const { types, regions, accountMap } = useMemo(() => {
    const types = typeCounts.data ? Object.keys(typeCounts.data).sort() : [];
    if (!accounts.data) return { types, regions: [] as string[], accountMap: new Map<number, string>() };
    const regionSet = new Set<string>();
    for (const a of accounts.data) {
      for (const r of a.regions ?? []) regionSet.add(r);
    }
    return {
      types,
      regions: [...regionSet].sort(),
      accountMap: new Map(accounts.data.map((a) => [a.id, a.name])),
    };
  }, [typeCounts.data, accounts.data]);

  const handleFilterChange = (setter: (v: string) => void, value: string) => {
    setter(value);
    setPage(1);
  };

  const columns: Column<Resource>[] = [
    {
      key: "provider",
      header: "Provider",
      sortable: true,
      sortValue: (r) => r.provider,
      render: (r) => (
        <span className="text-xs font-medium uppercase text-muted-foreground">{r.provider}</span>
      ),
    },
    {
      key: "account",
      header: "Account",
      sortable: true,
      sortValue: (r) => accountMap.get(r.account_id) ?? "",
      render: (r) => (
        <span className="text-sm text-muted-foreground">
          {accountMap.get(r.account_id) ?? "-"}
        </span>
      ),
    },
    {
      key: "resource_type",
      header: "Type",
      sortable: true,
      sortValue: (r) => r.resource_type,
      render: (r) => (
        <Badge className="bg-primary-100 text-primary-700">{r.resource_type}</Badge>
      ),
    },
    {
      key: "resource_id",
      header: "Resource ID",
      sortable: true,
      sortValue: (r) => r.resource_id,
      render: (r) => <span className="font-mono text-sm">{r.resource_id}</span>,
    },
    {
      key: "resource_name",
      header: "Name",
      sortable: true,
      sortValue: (r) => r.resource_name ?? "",
      render: (r) => r.resource_name ?? "-",
    },
    {
      key: "region",
      header: "Region",
      sortable: true,
      sortValue: (r) => r.region,
      render: (r) => <span className="text-sm text-muted-foreground">{r.region}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortValue: (r) => r.status,
      render: (r) => <StatusIndicator status={r.status} />,
    },
  ];

  return (
    <>
      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      )}

      {/* Filter bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-primary text-primary-foreground">
            {t("resources.title")}
            <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 text-xs rounded-full bg-primary-foreground/20 text-primary-foreground">
              {total}
            </span>
          </span>
          <select
            value={typeFilter}
            onChange={(e) => handleFilterChange(setTypeFilter, e.target.value)}
            className="text-sm font-medium rounded-lg px-3 py-1.5 bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent border-none transition-colors"
          >
            <option value="">All Types</option>
            {types.map((tp) => (
              <option key={tp} value={tp}>{tp}</option>
            ))}
          </select>
          <select
            value={regionFilter}
            onChange={(e) => handleFilterChange(setRegionFilter, e.target.value)}
            className="text-sm font-medium rounded-lg px-3 py-1.5 bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent border-none transition-colors"
          >
            <option value="">All Regions</option>
            {regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <select
            value={accountFilter}
            onChange={(e) => handleFilterChange(setAccountFilter, e.target.value)}
            className="text-sm font-medium rounded-lg px-3 py-1.5 bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent border-none transition-colors"
          >
            <option value="">All Accounts</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => handleFilterChange(setSearch, e.target.value)}
            placeholder={t("resources.search")}
            className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-64"
          />
        </div>
      </div>

      {/* Resource table */}
      {isLoading ? (
        <Spinner />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <DataTable
            columns={columns}
            data={items}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(`/app/resources/${r.id}`)}
            emptyMessage={t("dashboard.noResources")}
          />

          {total > 0 && (
            <div className="flex items-center justify-between border-t px-5 py-3">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Rows per page</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="border rounded-md px-2 py-1 bg-background text-sm"
                >
                  {PAGE_SIZES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground">
                  {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
                </span>
                <div className="flex gap-1">
                  <button onClick={() => setPage(1)} disabled={page <= 1} className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors">&laquo;</button>
                  <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors">&lsaquo;</button>
                  <span className="px-2 py-1 text-xs font-mono">{page} / {totalPages}</span>
                  <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors">&rsaquo;</button>
                  <button onClick={() => setPage(totalPages)} disabled={page >= totalPages} className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors">&raquo;</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
