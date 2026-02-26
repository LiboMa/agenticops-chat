import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Badge } from "@/components/ui/Badge";
import { formatShortDate } from "@/lib/formatDate";
import { useNotificationLogs, useNotificationChannels } from "@/hooks/useNotifications";
import type { NotificationLog } from "@/api/types";

const columns: Column<NotificationLog>[] = [
  {
    key: "subject",
    header: "Subject",
    render: (r) => (
      <span className="font-medium text-slate-900 max-w-xs truncate block">
        {r.subject}
      </span>
    ),
  },
  {
    key: "channel_id",
    header: "Channel",
    render: (r) => (
      <span className="font-mono text-sm text-slate-600">#{r.channel_id}</span>
    ),
  },
  {
    key: "severity",
    header: "Severity",
    render: (r) => {
      if (!r.severity) return <span className="text-slate-400">-</span>;
      const colors: Record<string, string> = {
        critical: "bg-red-100 text-red-700",
        high: "bg-orange-100 text-orange-700",
        medium: "bg-yellow-100 text-yellow-700",
        low: "bg-blue-100 text-blue-700",
      };
      return (
        <Badge className={colors[r.severity] ?? "bg-slate-100 text-slate-700"}>
          {r.severity}
        </Badge>
      );
    },
  },
  {
    key: "status",
    header: "Status",
    render: (r) =>
      r.status === "sent" ? (
        <Badge className="bg-green-100 text-green-700">sent</Badge>
      ) : (
        <Badge className="bg-red-100 text-red-700">{r.status}</Badge>
      ),
  },
  {
    key: "sent_at",
    header: "Sent At",
    sortable: true,
    sortValue: (r) => r.sent_at,
    render: (r) => (
      <span className="text-sm text-slate-500">{formatShortDate(r.sent_at)}</span>
    ),
  },
  {
    key: "error",
    header: "Error",
    render: (r) =>
      r.error ? (
        <span className="text-sm text-red-600 max-w-xs truncate block">{r.error}</span>
      ) : (
        <span className="text-slate-400">-</span>
      ),
  },
];

export default function NotificationLogs() {
  const [channelFilter, setChannelFilter] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const { data: channels } = useNotificationChannels();
  const { data: logs, isLoading, error } = useNotificationLogs({
    channel_id: channelFilter,
    status: statusFilter,
  });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <Link
            to="/app/notifications"
            className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 transition-colors"
          >
            <svg
              className="h-4 w-4 mr-1"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
            Channels
          </Link>
          <h2 className="text-lg font-semibold text-slate-900">Notification Logs</h2>
        </div>
        <div className="flex gap-2">
          <select
            value={channelFilter ?? ""}
            onChange={(e) =>
              setChannelFilter(e.target.value ? Number(e.target.value) : undefined)
            }
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">All Channels</option>
            {(channels ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={statusFilter ?? ""}
            onChange={(e) => setStatusFilter(e.target.value || undefined)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">All Statuses</option>
            <option value="sent">sent</option>
            <option value="failed">failed</option>
          </select>
        </div>
      </CardHeader>
      <DataTable
        columns={columns}
        data={logs ?? []}
        rowKey={(r) => r.id}
        emptyMessage="No notification logs found."
      />
    </Card>
  );
}
