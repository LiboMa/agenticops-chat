import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatCard } from "@/components/ui/StatCard";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useLocale } from "@/i18n/LocaleContext";
import { formatShortDate } from "@/lib/formatDate";
import { useAuditLog, useAuditStats } from "@/hooks/useAuditLog";
import type { AuditLogEntry } from "@/api/types";

const ACTION_OPTIONS = ["create", "update", "delete", "login", "login_failure", "logout"];
/** `system` = a change of PATCH /api/settings; `runtime_setting` = chat attachments / model connection. */
export const ENTITY_OPTIONS = ["account", "user", "api_key", "resource", "anomaly", "system", "runtime_setting", "readiness_check", "fix_plan", "change_request"];
const MAX_HOURS = 720;

type T = (key: string) => string;

const columns = (t: T): Column<AuditLogEntry>[] => [
  {
    key: "timestamp",
    header: t("audit.col.time"),
    sortable: true,
    sortValue: (r) => r.timestamp,
    render: (r) => (
      <span className="text-sm text-muted-foreground font-mono">{formatShortDate(r.timestamp)}</span>
    ),
  },
  {
    key: "action",
    header: t("audit.col.action"),
    render: (r) => (
      <span className="text-sm font-medium text-foreground">{r.action}</span>
    ),
  },
  {
    key: "entity_type",
    header: t("audit.col.entity"),
    render: (r) => (
      <span className="text-sm text-muted-foreground">
        {r.entity_type}
        {r.entity_id ? ` #${r.entity_id}` : ""}
      </span>
    ),
  },
  {
    key: "actor",
    header: t("audit.col.actor"),
    render: (a) => <span className="text-xs font-mono">{a.actor ?? a.user_email ?? "system"}</span>,
  },
  {
    key: "user_email",
    header: t("audit.col.user"),
    render: (r) => <span className="text-sm text-muted-foreground">{r.user_email}</span>,
  },
  {
    key: "details",
    header: t("audit.col.details"),
    render: (r) => <DetailsCell details={r.details} change={changeSummary(r.old_values, r.new_values)} />,
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

/** What a row changed, from its old and new values: `executor_enabled: false → true` (MVP-2.9.0 N25 — a settings
 *  change carries no `details`, only the value before and after). null when the row records neither. */
export function changeSummary(oldValues: Record<string, unknown> | null | undefined, newValues: Record<string, unknown> | null | undefined): string | null {
  if (isEmptyDetails(oldValues) && isEmptyDetails(newValues)) return null;
  const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));
  const keys = [...new Set([...Object.keys(oldValues ?? {}), ...Object.keys(newValues ?? {})])].sort();
  return keys.map((key) => `${key}: ${show(oldValues?.[key])} → ${show(newValues?.[key])}`).join("; ");
}

/** `details` arrives as a dict, and React throws on an object child: a string (legacy rows) as-is, a dict as JSON
 *  cut to DETAILS_MAX_CHARS with the full JSON in the tooltip; a row without details shows what it changed (old →
 *  new); "-" when it has neither. */
function DetailsCell({ details, change }: { details: unknown; change: string | null }) {
  if (isEmptyDetails(details)) {
    return change === null ? <span className="text-sm text-muted-foreground">-</span>
      : <span className="text-sm text-muted-foreground [overflow-wrap:anywhere]" title={change}>{change.length > DETAILS_MAX_CHARS ? `${change.slice(0, DETAILS_MAX_CHARS)}…` : change}</span>;
  }
  if (typeof details === "string") return <span className="text-sm text-muted-foreground">{details}</span>;
  const json = JSON.stringify(details);
  return (
    <span className="text-sm text-muted-foreground" title={json}>
      {json.length > DETAILS_MAX_CHARS ? `${json.slice(0, DETAILS_MAX_CHARS)}…` : json}
    </span>
  );
}

/** The filters an address asks for (`?tab=audit&entity=system&hours=720` — the Settings page's link to the records
 *  of settings changes): a known entity type, 1–720 hours; anything else is the default. */
export function auditFilters(params: URLSearchParams): { entity: string; hours: number } {
  const entity = params.get("entity") ?? "";
  const hours = Number(params.get("hours"));
  return { entity: ENTITY_OPTIONS.includes(entity) ? entity : "",
           hours: Number.isInteger(hours) && hours >= 1 && hours <= MAX_HOURS ? hours : 24 };
}

export function AuditTab() {
  const { t } = useLocale();
  const [params] = useSearchParams();
  const asked = auditFilters(params);
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState(asked.entity);
  const [hours, setHours] = useState(asked.hours);

  const { data: entries, isLoading, error, refetch } = useAuditLog({
    action: action || undefined,
    entity_type: entityType || undefined,
    hours,
  });
  const { data: stats } = useAuditStats(hours);

  if (isLoading) return <Spinner label={t("common.loading")} />;
  if (error) return <ErrorBanner message={`${t("audit.failed")} · ${(error as Error).message}`} onRetry={() => void refetch()} actionLabel={t("common.retry")} />;
  const select = "text-[16px] sm:text-sm border border-border rounded-lg px-2 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500";

  return (
    <div className="space-y-6">
      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard label={t("audit.total")} value={stats.total_events} />
          <StatCard label={t("audit.creates")} value={stats.creates} colorClass="text-green-600" />
          <StatCard label={t("audit.updates")} value={stats.updates} colorClass="text-blue-600" />
          <StatCard label={t("audit.deletes")} value={stats.deletes} colorClass="text-red-600" />
          <StatCard label={t("audit.logins")} value={stats.logins} colorClass="text-foreground" />
          <StatCard label={t("audit.loginFailures")} value={stats.login_failures} colorClass="text-orange-600" />
        </div>
      )}

      {/* Filter bar */}
      <Card>
        <CardHeader className="flex-wrap gap-2">
          <h2 className="text-lg font-semibold text-foreground">{t("audit.title")}</h2>
          <div className="flex flex-wrap items-center gap-3">
            <select aria-label={t("audit.col.action")} value={action} onChange={(e) => setAction(e.target.value)} className={select}>
              <option value="">{t("audit.allActions")}</option>
              {ACTION_OPTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select aria-label={t("audit.col.entity")} value={entityType} onChange={(e) => setEntityType(e.target.value)} className={select}>
              <option value="">{t("audit.allEntities")}</option>
              {ENTITY_OPTIONS.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
            <div className="flex items-center gap-1">
              <label htmlFor="audit-hours" className="text-sm text-muted-foreground">{t("audit.hours")}</label>
              <input
                id="audit-hours"
                type="number"
                min={1}
                max={MAX_HOURS}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value) || 24)}
                className={`w-20 ${select}`}
              />
            </div>
          </div>
        </CardHeader>
        <DataTable
          columns={columns(t)}
          data={entries ?? []}
          rowKey={(r) => r.id}
          emptyMessage={t("audit.empty")}
        />
      </Card>
    </div>
  );
}
