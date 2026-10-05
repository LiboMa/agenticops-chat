import { useState, useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useLocale } from "@/i18n/LocaleContext";
import { WorkItemTable } from "@/components/ui/WorkItemTable";
import { IssueQuickActions } from "@/components/ui/IssueQuickActions";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { SignalsPanel } from "@/components/signals/SignalsPanel";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ISSUE_SCOPES, resolveIssueScope, type IssueScope } from "@/lib/issueScope";
import { issueRow } from "@/lib/workItems";
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
        <IssuesView t={t} />
      ) : view === "signals" ? (
        <SignalsPanel />
      ) : (
        <ResourcesView navigate={navigate} t={t} initialType={searchParams.get("type") || ""} />
      )}
    </div>
  );
}

/* ── Issues View ────────────────────────────────────────────────── */

const selectClass =
  "text-sm font-medium rounded-lg px-3 py-1.5 bg-secondary text-muted-foreground hover:text-foreground hover:bg-accent border-none transition-colors cursor-pointer";

function IssuesView({ t }: { t: (key: string) => string }) {
  const [phase, setPhase] = useState<Phase>("all");
  const [severity, setSeverity] = useState<Severity>("all");
  const [account, setAccount] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [search, setSearch] = useState("");
  // The view lives in the URL (ops events by default) and filters on the server: the list is paged.
  const [searchParams, setSearchParams] = useSearchParams();
  const scope = resolveIssueScope(searchParams.get("scope"));
  const setScope = (s: IssueScope) => setSearchParams(s === "ops" ? {} : { scope: s });
  const { data, isLoading, error, refetch } = useAnomalies({ scope, account_id: account ? Number(account) : undefined });
  const accounts = useAccounts();

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

  // The rows carry only strings (issueRow is pure); the quick actions need the issue itself.
  const byKey = useMemo(() => new Map(filtered.map((a) => [`I${a.id}`, a])), [filtered]);

  const phases: { key: Phase; label: string; count: number }[] = [
    { key: "all", label: t("issues.all"), count: counts.all },
    { key: "active", label: t("issues.active"), count: counts.active },
    { key: "resolved", label: t("issues.resolved"), count: counts.resolved },
    { key: "dismissed", label: t("issues.dismissed"), count: counts.dismissed },
  ];
  // The selected option is all a closed <select> shows, so each option names its filter.
  const named = (filterKey: string, label: string) =>
    t("workitem.filter.named").replace("{filter}", t(filterKey)).replace("{value}", label);

  return (
    <>
      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} actionLabel={t("common.retry")} />
      )}

      {/* Filters: one row (P15) */}
      <div className="flex flex-wrap items-center gap-2">
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
            className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-56"
          />
        </div>
        <select value={phase} onChange={(e) => setPhase(e.target.value as Phase)} aria-label={t("workitem.filter.status")} className={selectClass}>
          {phases.map((p) => (
            <option key={p.key} value={p.key}>{named("workitem.filter.status", `${p.label} (${p.count})`)}</option>
          ))}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)} aria-label={t("workitem.filter.severity")} className={selectClass}>
          {(["all", "critical", "high", "medium", "low"] as Severity[]).map((sev) => (
            <option key={sev} value={sev}>
              {named("workitem.filter.severity", `${sev === "all" ? t("issues.all") : sev} (${sevCounts[sev] ?? 0})`)}
            </option>
          ))}
        </select>
        <select value={scope} onChange={(e) => setScope(e.target.value as IssueScope)} aria-label={t("workitem.filter.scope")} className={selectClass}>
          {ISSUE_SCOPES.map((s) => (
            <option key={s} value={s}>{named("workitem.filter.scope", t(`issues.scope.${s}`))}</option>
          ))}
        </select>
        <select value={account} onChange={(e) => setAccount(e.target.value)} aria-label={t("workitem.filter.account")} className={selectClass}>
          <option value="">{named("workitem.filter.account", t("issues.all"))}</option>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>{named("workitem.filter.account", a.name)}</option>
          ))}
        </select>
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} className={selectClass}>
          <option value="newest">{t("issues.sortNewest")}</option>
          <option value="oldest">{t("issues.sortOldest")}</option>
          <option value="severity">{t("issues.sortSeverity")}</option>
        </select>
        <Link to="/app/signals" className="ml-auto text-sm text-primary hover:underline">{t("workitem.rawSignals")}</Link>
      </div>

      {/* Issue list */}
      {isLoading ? (
        <Spinner />
      ) : (
        <WorkItemTable
          rows={filtered.map(issueRow)}
          levelHeader={t("facts.severity")}
          renderLevel={(r) => <SeverityBadge severity={r.level as Anomaly["severity"]} />}
          rowActions={(r) => { const a = byKey.get(r.key); return a ? <IssueQuickActions issue={a} /> : null; }}
          emptyMessage={t("issues.noIssues")}
          t={t}
        />
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
  const [showAbsent, setShowAbsent] = useState(false);
  const accounts = useAccounts();
  const typeCounts = useResourceTypeCounts(showAbsent);

  const offset = (page - 1) * pageSize;

  const { data, isLoading, error, refetch } = useResources({
    type: typeFilter || undefined,
    region: regionFilter || undefined,
    account_id: accountFilter ? Number(accountFilter) : undefined,
    search: search || undefined,
    limit: pageSize,
    offset,
    includeAbsent: showAbsent,
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
      render: (r) => (
        <span
          className={`font-mono text-sm${r.absent_since ? " line-through opacity-60" : ""}`}
          title={r.absent_since ? t("resources.absent") : undefined}
        >
          {r.resource_id}
        </span>
      ),
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
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={showAbsent}
              onChange={(e) => {
                setShowAbsent(e.target.checked);
                setPage(1);
              }}
              className="rounded border-border"
            />
            {t("resources.showAbsent")}
          </label>
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
