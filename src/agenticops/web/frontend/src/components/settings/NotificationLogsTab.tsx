import { useState } from "react";
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
      <span className="font-medium text-foreground max-w-xs truncate block">
        {r.subject}
      </span>
    ),
  },
  {
    key: "channel_name",
    header: "Channel",
    render: (r) => (
      <span className="font-mono text-sm text-muted-foreground">{r.channel_name}</span>
    ),
  },
  {
    key: "severity",
    header: "Severity",
    render: (r) => {
      if (!r.severity) return <span className="text-muted-foreground">-</span>;
      const colors: Record<string, string> = {
        critical: "bg-red-100 text-red-700",
        high: "bg-orange-100 text-orange-700",
        medium: "bg-yellow-100 text-yellow-700",
        low: "bg-blue-100 text-blue-700",
      };
      return (
        <Badge className={colors[r.severity] ?? "bg-secondary text-foreground"}>
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
      <span className="text-sm text-muted-foreground">{formatShortDate(r.sent_at)}</span>
    ),
  },
  {
    key: "error",
    header: "Error",
    render: (r) =>
      r.error ? (
        <span className="text-sm text-red-600 max-w-xs truncate block">{r.error}</span>
      ) : (
        <span className="text-muted-foreground">-</span>
      ),
  },
];

export function NotificationLogsTab() {
  const [channelFilter, setChannelFilter] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const { data: channels } = useNotificationChannels();
  const { data: logs, isLoading, error } = useNotificationLogs({
    channel_name: channelFilter,
    status: statusFilter,
  });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-semibold text-foreground">Notification Logs</h2>
        <div className="flex gap-2">
          <select
            value={channelFilter ?? ""}
            onChange={(e) =>
              setChannelFilter(e.target.value || undefined)
            }
            className="px-3 py-1.5 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">All Channels</option>
            {(channels ?? []).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={statusFilter ?? ""}
            onChange={(e) => setStatusFilter(e.target.value || undefined)}
            className="px-3 py-1.5 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
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
