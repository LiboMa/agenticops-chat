import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatCard } from "@/components/ui/StatCard";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import { useAuditLog, useAuditStats } from "@/hooks/useAuditLog";
import type { AuditLogEntry } from "@/api/types";

const ACTION_OPTIONS = ["", "create", "update", "delete", "login", "login_failure", "logout"];
const ENTITY_OPTIONS = ["", "account", "user", "api_key", "resource", "anomaly"];

const columns: Column<AuditLogEntry>[] = [
  {
    key: "timestamp",
    header: "Time",
    sortable: true,
    sortValue: (r) => r.timestamp,
    render: (r) => (
      <span className="text-sm text-muted-foreground font-mono">{formatShortDate(r.timestamp)}</span>
    ),
  },
  {
    key: "action",
    header: "Action",
    render: (r) => (
      <span className="text-sm font-medium text-foreground">{r.action}</span>
    ),
  },
  {
    key: "entity_type",
    header: "Entity",
    render: (r) => (
      <span className="text-sm text-muted-foreground">
        {r.entity_type}
        {r.entity_id ? ` #${r.entity_id}` : ""}
      </span>
    ),
  },
  {
    key: "actor",
    header: "Actor",
    render: (a) => <span className="text-xs font-mono">{a.actor ?? a.user_email ?? "system"}</span>,
  },
  {
    key: "user_email",
    header: "User",
    render: (r) => <span className="text-sm text-muted-foreground">{r.user_email}</span>,
  },
  {
    key: "details",
    header: "Details",
    render: (r) => <DetailsCell details={r.details} />,
  },
];

const DETAILS_MAX_CHARS = 120;

/** null, undefined, or an object with no own keys (the ORM default `{}`) — all render as "-". */
export function isEmptyDetails(details: unknown): boolean {
  return (
    details === null ||
    details === undefined ||
    (typeof details === "object" && Object.keys(details as object).length === 0)
  );
}

/** `details` arrives as a dict, and React throws on an object child: "-" for empty (null/undefined/`{}`),
 *  a string (legacy rows) as-is, anything else as JSON cut to DETAILS_MAX_CHARS with the full JSON in the tooltip. */
function DetailsCell({ details }: { details: unknown }) {
  if (isEmptyDetails(details)) return <span className="text-sm text-muted-foreground">-</span>;
  if (typeof details === "string") return <span className="text-sm text-muted-foreground">{details}</span>;
  const json = JSON.stringify(details);
  return (
    <span className="text-sm text-muted-foreground" title={json}>
      {json.length > DETAILS_MAX_CHARS ? `${json.slice(0, DETAILS_MAX_CHARS)}…` : json}
    </span>
  );
}

export function AuditTab() {
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [hours, setHours] = useState(24);

  const { data: entries, isLoading, error } = useAuditLog({
    action: action || undefined,
    entity_type: entityType || undefined,
    hours,
  });
  const { data: stats } = useAuditStats(hours);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={(error as Error).message} />;

  return (
    <div className="space-y-6">
      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard label="Total Events" value={stats.total_events} />
          <StatCard label="Creates" value={stats.creates} colorClass="text-green-600" />
          <StatCard label="Updates" value={stats.updates} colorClass="text-blue-600" />
          <StatCard label="Deletes" value={stats.deletes} colorClass="text-red-600" />
          <StatCard label="Logins" value={stats.logins} colorClass="text-foreground" />
          <StatCard
            label="Login Failures"
            value={stats.login_failures}
            colorClass="text-orange-600"
          />
        </div>
      )}

      {/* Filter bar */}
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-foreground">Audit Log</h2>
          <div className="flex items-center gap-3">
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="text-sm border border-border rounded-lg px-2 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Actions</option>
              {ACTION_OPTIONS.filter(Boolean).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="text-sm border border-border rounded-lg px-2 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="">All Entities</option>
              {ENTITY_OPTIONS.filter(Boolean).map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-1">
              <label className="text-sm text-muted-foreground">Hours:</label>
              <input
                type="number"
                min={1}
                max={720}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value) || 24)}
                className="w-16 text-sm border border-border rounded-lg px-2 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
          </div>
        </CardHeader>
        <DataTable
          columns={columns}
          data={entries ?? []}
          rowKey={(r) => r.id}
          emptyMessage="No audit entries found."
        />
      </Card>
    </div>
  );
}
