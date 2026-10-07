import { useState, useMemo } from "react";
import type { useNavigate } from "react-router-dom";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useScopedAccountId } from "@/components/layout/AccountScope";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Resource } from "@/api/types";

/* The issue list moved to pages/Cases (MVP-2.7.0 S4); the resources table stays here until it gets its own page. */

const PAGE_SIZES = [50, 100, 200];

export function ResourcesView({
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
    account_id: useScopedAccountId(),
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
