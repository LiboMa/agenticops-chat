import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAnomalies } from "@/hooks/useAnomalies";
import { Card, CardHeader } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { Anomaly } from "@/api/types";

export default function Anomalies() {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const navigate = useNavigate();

  const { data, isLoading, error, refetch } = useAnomalies({
    severity: severity || undefined,
    status: status || undefined,
  });

  const columns: Column<Anomaly>[] = [
    {
      key: "id",
      header: "#",
      sortable: true,
      sortValue: (a) => a.id,
      render: (a) => (
        <span className="font-mono text-sm text-primary-600 font-medium">
          I#{a.id}
        </span>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      sortable: true,
      sortValue: (a) => {
        const order = { critical: 0, high: 1, medium: 2, low: 3 };
        return order[a.severity] ?? 4;
      },
      render: (a) => <SeverityBadge severity={a.severity} />,
    },
    {
      key: "title",
      header: "Title",
      sortable: true,
      sortValue: (a) => a.title,
      render: (a) => (
        <span className="font-medium text-slate-900">{a.title}</span>
      ),
    },
    {
      key: "resource",
      header: "Resource",
      render: (a) => (
        <span className="text-sm text-slate-500 font-mono">
          {a.resource_type}/{a.resource_id.slice(0, 20)}
        </span>
      ),
    },
    {
      key: "region",
      header: "Region",
      sortable: true,
      sortValue: (a) => a.region,
      render: (a) => <span className="text-sm text-slate-500">{a.region}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortValue: (a) => a.status,
      render: (a) => <IssueStatusBadge status={a.status} />,
    },
    {
      key: "detected_at",
      header: "Detected",
      sortable: true,
      sortValue: (a) => a.detected_at,
      render: (a) => (
        <span className="text-sm text-slate-500">
          {formatShortDate(a.detected_at)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {error && (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      )}

      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-slate-900">
            Issues{data ? ` (${data.length})` : ""}
          </h2>
          <div className="flex items-center gap-2">
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Statuses</option>
              <option value="open">Open</option>
              <option value="investigating">Investigating</option>
              <option value="root_cause_identified">RCA Complete</option>
              <option value="fix_planned">Fix Planned</option>
              <option value="fix_approved">Fix Approved</option>
              <option value="fix_executed">Fix Executed</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>
        </CardHeader>

        {isLoading ? (
          <Spinner />
        ) : (
          <DataTable
            columns={columns}
            data={data ?? []}
            rowKey={(a) => a.id}
            onRowClick={(a) => navigate(`/app/issues/${a.id}`)}
            emptyMessage="No issues found."
          />
        )}
      </Card>
    </div>
  );
}
