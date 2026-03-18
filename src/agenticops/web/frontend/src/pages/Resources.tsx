import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useResources } from "@/hooks/useResources";
import { useAccounts } from "@/hooks/useAccounts";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Resource } from "@/api/types";

const PAGE_SIZES = [50, 100, 200];

export default function Resources() {
  const navigate = useNavigate();
  const [typeFilter, setTypeFilter] = useState("");
  const [regionFilter, setRegionFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const accounts = useAccounts();
  const typeCounts = useResourceTypeCounts();

  const offset = (page - 1) * pageSize;

  const { data, isLoading, error, refetch } = useResources({
    type: typeFilter || undefined,
    region: regionFilter || undefined,
    account_id: accountFilter ? Number(accountFilter) : undefined,
    limit: pageSize,
    offset,
  });

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Types from type-counts endpoint (no limit)
  const types = useMemo(() => {
    if (!typeCounts.data) return [];
    return Object.keys(typeCounts.data).sort();
  }, [typeCounts.data]);

  // Regions from accounts
  const regions = useMemo(() => {
    if (!accounts.data) return [];
    const regionSet = new Set<string>();
    for (const a of accounts.data) {
      for (const r of a.regions ?? []) regionSet.add(r);
    }
    return [...regionSet].sort();
  }, [accounts.data]);

  // Build account name lookup
  const accountMap = useMemo(() => {
    if (!accounts.data) return new Map<number, string>();
    return new Map(accounts.data.map((a) => [a.id, a.name]));
  }, [accounts.data]);

  // Reset to page 1 when filters change
  const handleFilterChange = (
    setter: (v: string) => void,
    value: string,
  ) => {
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
        <Badge className="bg-primary-100 text-primary-700">
          {r.resource_type}
        </Badge>
      ),
    },
    {
      key: "resource_id",
      header: "Resource ID",
      sortable: true,
      sortValue: (r) => r.resource_id,
      render: (r) => (
        <span className="font-mono text-sm">{r.resource_id}</span>
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
    <div className="space-y-4">
      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      )}

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold">
            Resources ({total})
          </h2>
          <div className="flex gap-2">
            <select
              value={typeFilter}
              onChange={(e) => handleFilterChange(setTypeFilter, e.target.value)}
              className="text-sm border rounded-md px-3 py-1.5 bg-background"
            >
              <option value="">All Types</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              value={regionFilter}
              onChange={(e) => handleFilterChange(setRegionFilter, e.target.value)}
              className="text-sm border rounded-md px-3 py-1.5 bg-background"
            >
              <option value="">All Regions</option>
              {regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <select
              value={accountFilter}
              onChange={(e) => handleFilterChange(setAccountFilter, e.target.value)}
              className="text-sm border rounded-md px-3 py-1.5 bg-background"
            >
              <option value="">All Accounts</option>
              {(accounts.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        </CardHeader>

        {isLoading ? (
          <Spinner />
        ) : (
          <>
            <DataTable
              columns={columns}
              data={items}
              rowKey={(r) => r.id}
              onRowClick={(r) => navigate(`/app/resources/${r.id}`)}
              emptyMessage="No resources found."
            />

            {/* Pagination */}
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
                    <button
                      onClick={() => setPage(1)}
                      disabled={page <= 1}
                      className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors"
                    >
                      &laquo;
                    </button>
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors"
                    >
                      &lsaquo;
                    </button>
                    <span className="px-2 py-1 text-xs font-mono">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page >= totalPages}
                      className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors"
                    >
                      &rsaquo;
                    </button>
                    <button
                      onClick={() => setPage(totalPages)}
                      disabled={page >= totalPages}
                      className="px-2 py-1 rounded-md border text-xs disabled:opacity-30 hover:bg-accent transition-colors"
                    >
                      &raquo;
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
