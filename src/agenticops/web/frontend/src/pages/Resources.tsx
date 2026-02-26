import { useState, useMemo } from "react";
import { useResources } from "@/hooks/useResources";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import type { Resource } from "@/api/types";

export default function Resources() {
  const [typeFilter, setTypeFilter] = useState("");
  const [regionFilter, setRegionFilter] = useState("");

  const { data, isLoading, error, refetch } = useResources({
    type: typeFilter || undefined,
    region: regionFilter || undefined,
    limit: 500,
  });

  // Extract unique types and regions for filter dropdowns
  const allResources = useResources({ limit: 500 });
  const { types, regions } = useMemo(() => {
    if (!allResources.data) return { types: [], regions: [] };
    const typeSet = new Set<string>();
    const regionSet = new Set<string>();
    for (const r of allResources.data) {
      typeSet.add(r.resource_type);
      regionSet.add(r.region);
    }
    return {
      types: [...typeSet].sort(),
      regions: [...regionSet].sort(),
    };
  }, [allResources.data]);

  const columns: Column<Resource>[] = [
    {
      key: "resource_type",
      header: "Type",
      sortable: true,
      sortValue: (r) => r.resource_type,
      render: (r) => (
        <Badge className="bg-indigo-100 text-indigo-800">
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
      render: (r) => <span className="text-sm text-gray-500">{r.region}</span>,
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
          <h2 className="text-lg font-semibold text-gray-900">
            Resources{data ? ` (${data.length})` : ""}
          </h2>
          <div className="flex gap-2">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-pd-green-500"
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
              onChange={(e) => setRegionFilter(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-pd-green-500"
            >
              <option value="">All Regions</option>
              {regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </CardHeader>

        {isLoading ? (
          <Spinner />
        ) : (
          <DataTable
            columns={columns}
            data={data ?? []}
            rowKey={(r) => r.id}
            emptyMessage="No resources found."
          />
        )}
      </Card>
    </div>
  );
}
