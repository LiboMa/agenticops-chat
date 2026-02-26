import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useReports } from "@/hooks/useReports";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { Report } from "@/api/types";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700",
  incident: "bg-red-100 text-red-700",
  inventory: "bg-emerald-100 text-emerald-700",
  weekly: "bg-purple-100 text-purple-700",
};

const columns: Column<Report>[] = [
  {
    key: "report_type",
    header: "Type",
    render: (r) => (
      <Badge
        className={TYPE_COLORS[r.report_type] ?? "bg-slate-100 text-slate-600"}
      >
        {r.report_type}
      </Badge>
    ),
    className: "w-28",
  },
  {
    key: "title",
    header: "Title",
    render: (r) => (
      <span className="text-sm font-medium text-slate-900">{r.title}</span>
    ),
  },
  {
    key: "summary",
    header: "Summary",
    render: (r) => (
      <span className="text-sm text-slate-600 line-clamp-2">
        {r.summary}
      </span>
    ),
  },
  {
    key: "created_at",
    header: "Created",
    sortable: true,
    sortValue: (r) => new Date(r.created_at).getTime(),
    render: (r) => (
      <span className="text-sm text-slate-500">
        {formatShortDate(r.created_at)}
      </span>
    ),
    className: "w-36",
  },
];

export default function Reports() {
  const { data, isLoading, error, refetch } = useReports();
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter(
      (r) =>
        r.title.toLowerCase().includes(q) ||
        r.summary.toLowerCase().includes(q),
    );
  }, [data, search]);

  if (isLoading) return <Spinner label="Loading reports..." />;
  if (error)
    return <ErrorBanner message={error.message} onRetry={() => refetch()} />;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">Reports</h2>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search reports..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 w-64 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <span className="text-sm text-slate-400">
              {filtered.length} reports
            </span>
          </div>
        </CardHeader>
        <CardBody className="p-0">
          <DataTable
            columns={columns}
            data={filtered}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(`/app/reports/${r.id}`)}
            emptyMessage="No reports found."
          />
        </CardBody>
      </Card>
    </div>
  );
}
