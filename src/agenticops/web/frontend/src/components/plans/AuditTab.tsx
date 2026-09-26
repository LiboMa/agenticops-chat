import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar, CartesianGrid, Cell, ComposedChart, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { usePlanStats } from "@/hooks/usePlanStats";
import { useAuditLog } from "@/hooks/useAuditLog";
import { useCommandAudits } from "@/hooks/useCommandAudits";
import { useSettings } from "@/hooks/useSettings";
import { useAccounts } from "@/hooks/useAccounts";
import { useLocale } from "@/i18n/LocaleContext";
import { StatCard } from "@/components/ui/StatCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { PeriodButtons } from "@/components/plans/PeriodButtons";
import { formatFullDate, parseApiDate } from "@/lib/formatDate";
import { fillDailySeries, fmtRate, fmtSecs, isForbidden, mergeDecisionRows, type KindFilter } from "@/lib/auditLedger";
import type { Period } from "@/lib/plans";
import type { AuditLogEntry, CommandAudit } from "@/api/types";

const HOURS: Record<Period, number> = { "7d": 168, "30d": 720, "90d": 2160 }; // T11 raised /api/audit's cap to 2160 h
const LEDGER_LIMIT = 500; // /api/audit's limit cap (max_list_limit)
const COMMAND_LIMIT = 200;
const RISK_COLORS: Record<string, string> = { L0: "#10b981", L1: "#3b82f6", L2: "#f59e0b", L3: "#ef4444" };
const SERIES_COLORS = { created: "#3b82f6", completed: "#10b981", failed: "#ef4444" };

/** A non-empty string at `key` in an audit row's details, else null (details may be null or a legacy string). */
function detailStr(details: AuditLogEntry["details"], key: string): string | null {
  if (!details || typeof details !== "object") return null;
  const v = (details as Record<string, unknown>)[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

/** Count dicts sort by count descending, then key ascending. */
function sortedEntries(dict: Record<string, number>): [string, number][] {
  return Object.entries(dict).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

function StatList({ title, rows }: { title: string; rows: { label: ReactNode; value: ReactNode }[] }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground mb-1">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-muted-foreground">-</div>
      ) : (
        rows.map((r, i) => (
          <div key={i} className="flex justify-between text-xs">
            <span>{r.label}</span>
            <span>{r.value}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function AuditTab() {
  const { t } = useLocale();
  const changesOn = useSettings().data?.change_management_enabled === true;
  const [period, setPeriod] = useState<Period>("30d");
  const [kind, setKind] = useState<KindFilter>("all");
  const effKind: KindFilter = changesOn ? kind : "fix"; // flag off → fix work only; change widgets hidden (T12 r8)

  const stats = usePlanStats({ period, kind: effKind });
  const q1 = useAuditLog({ hours: HOURS[period], limit: LEDGER_LIMIT, entity_type: "change_request" });
  const q2 = useAuditLog({ hours: HOURS[period], limit: LEDGER_LIMIT, entity_type: "fix_plan" });
  const q3 = useAuditLog({ hours: HOURS[period], limit: LEDGER_LIMIT, entity_type: "system" });
  const commands = useCommandAudits({ period, limit: COMMAND_LIMIT });
  const accounts = useAccounts();

  const ledger = useMemo(
    () => mergeDecisionRows([q1.data, q2.data, q3.data], effKind, LEDGER_LIMIT),
    [q1.data, q2.data, q3.data, effKind],
  );

  const statsForbidden = isForbidden(stats.error);
  const decisionLoading = q1.isLoading || q2.isLoading || q3.isLoading;
  const decisionError = q1.error || q2.error || q3.error;
  const refetchDecisions = () => { q1.refetch(); q2.refetch(); q3.refetch(); };

  const accountName = (key: string) => accounts.data?.find((a) => a.id === Number(key))?.name ?? `#${key}`;

  const entityCell = (entity_type: string, entity_id: string) => {
    if (entity_type === "change_request") {
      const label = `C#${entity_id}`;
      return changesOn
        ? <Link to={`/app/changes/${entity_id}`} className="text-xs font-mono text-primary hover:underline">{label}</Link>
        : <span className="text-xs font-mono">{label}</span>;
    }
    if (entity_type === "fix_plan") return <span className="text-xs font-mono">plan #{entity_id}</span>;
    const hasId = entity_id !== "-" && entity_id !== "";
    return <span className="text-xs font-mono">{entity_type}{hasId ? `#${entity_id}` : ""}</span>;
  };

  const dcols: Column<AuditLogEntry>[] = [
    {
      key: "ts", header: t("audit.col.time"), sortable: true,
      sortValue: (a) => parseApiDate(a.timestamp)?.getTime() ?? 0,
      render: (a) => <span className="text-xs text-muted-foreground">{formatFullDate(a.timestamp)}</span>,
    },
    {
      key: "actor", header: t("audit.col.actor"),
      render: (a) => {
        const claimed = detailStr(a.details, "claimed_name");
        return (
          <span className="text-xs font-mono">
            {a.actor ?? a.user_email ?? "system"}
            {claimed && <span className="text-muted-foreground">{` ${t("audit.claimedAs").replace("{name}", claimed)}`}</span>}
          </span>
        );
      },
    },
    {
      key: "action", header: t("audit.col.action"), sortable: true, sortValue: (a) => a.action,
      render: (a) => {
        const perm = detailStr(a.details, "permission");
        return <span className="text-xs font-mono">{a.action}{perm ? ` · ${perm}` : ""}</span>;
      },
    },
    { key: "entity", header: t("audit.col.entity"), render: (a) => entityCell(a.entity_type, a.entity_id) },
    {
      key: "reason", header: t("plans.reason"),
      render: (a) => {
        const reason = detailStr(a.details, "reason");
        if (!reason) return <span className="text-xs text-muted-foreground">-</span>;
        const cut = reason.length > 80 ? `${reason.slice(0, 80)}…` : reason;
        return <span className="text-xs text-muted-foreground" title={reason}>{cut}</span>;
      },
    },
  ];

  const ccols: Column<CommandAudit>[] = [
    {
      key: "ts", header: t("audit.col.time"), sortable: true,
      sortValue: (c) => parseApiDate(c.created_at)?.getTime() ?? 0,
      render: (c) => <span className="text-xs text-muted-foreground">{formatFullDate(c.created_at)}</span>,
    },
    {
      key: "actor", header: t("audit.col.actor"),
      render: (c) => (
        <span className="text-xs font-mono">
          {c.actor}{c.on_behalf_of ? ` ${t("audit.onBehalfOf").replace("{name}", c.on_behalf_of)}` : ""}
        </span>
      ),
    },
    { key: "tool", header: t("audit.col.tool"), render: (c) => <span className="text-xs font-mono">{c.tool}</span> },
    {
      key: "outcome", header: t("audit.col.outcome"), sortable: true, sortValue: (c) => c.outcome,
      render: (c) => {
        const color = c.outcome === "executed" ? "text-emerald-500"
          : c.outcome === "refused" || c.outcome === "blocked" ? "text-amber-500" : "text-red-500";
        return <span className={`text-xs font-medium ${color}`}>{c.outcome}{c.reason ? ` · ${c.reason}` : ""}</span>;
      },
    },
    {
      key: "cmd", header: t("audit.col.command"),
      render: (c) => {
        const cut = c.command.length > 120 ? `${c.command.slice(0, 120)}…` : c.command;
        return <code className="text-[11px] break-all" title={c.command}>{cut}</code>;
      },
    },
    {
      key: "ref", header: t("audit.col.ref"),
      render: (c) => {
        if (c.change_request_id) {
          const label = `C#${c.change_request_id}`;
          return changesOn
            ? <Link to={`/app/changes/${c.change_request_id}`} className="text-xs font-mono text-primary hover:underline">{label}</Link>
            : <span className="text-xs font-mono">{label}</span>;
        }
        if (c.fix_plan_id) return <span className="text-xs font-mono">plan #{c.fix_plan_id}</span>;
        return <span className="text-xs text-muted-foreground">-</span>;
      },
    },
  ];

  const s = stats.data;
  const createdTotal = s
    ? Object.values(s.totals.by_kind_status).reduce((sum, statuses) => sum + Object.values(statuses).reduce((a, b) => a + b, 0), 0)
    : 0;
  const seriesData = s ? fillDailySeries(s.series, s.period.start, s.period.end) : [];
  const seriesEmpty = seriesData.every((r) => r.created === 0 && r.completed === 0 && r.failed === 0);
  const riskData = s
    ? Object.entries(s.breakdown.by_risk).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([name, value]) => ({ name, value }))
    : [];
  const approvalsLine = s
    ? t("audit.approvalsLine")
        .replace("{auto}", String(s.approvals.auto))
        .replace("{human}", String(s.approvals.human))
        .replace("{rejected}", String(s.approvals.rejected))
        .replace("{denied}", String(s.approvals.authz_denied))
        .replace("{shadow}", String(s.approvals.authz_denied_shadow))
    : null;

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <PeriodButtons value={period} onChange={(p) => p && setPeriod(p)} />
        {changesOn && (
          <div className="flex gap-1 bg-secondary rounded-lg p-1">
            {(["all", "fix", "change"] as KindFilter[]).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={`px-2 py-1 text-xs rounded ${kind === k ? "bg-background shadow text-foreground" : "text-muted-foreground"}`}
              >{t(`plans.kind.${k}`)}</button>
            ))}
          </div>
        )}
      </div>

      {statsForbidden ? (
        <p className="text-sm text-muted-foreground">{t("audit.adminOnly")}</p>
      ) : (
        <>
          {/* Stats: KPIs, charts, breakdown */}
          {stats.isLoading ? (
            <Spinner label={t("common.loading")} />
          ) : stats.error || !s ? (
            <ErrorBanner message={(stats.error as Error)?.message ?? t("common.error")} onRetry={() => stats.refetch()} actionLabel={t("common.retry")} />
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
                <StatCard label={t("audit.kpi.created")} value={createdTotal} />
                <StatCard label={t("audit.kpi.open")} value={s.totals.open} />
                <StatCard label={t("audit.kpi.successRate")} value={fmtRate(s.outcomes.success_rate)} colorClass="text-emerald-500" />
                <StatCard label={t("audit.kpi.leadTime")} value={`${fmtSecs(s.lead_time.request_to_approve_p50_s)} / ${fmtSecs(s.lead_time.request_to_approve_p90_s)}`} />
                <StatCard label={t("audit.kpi.rollbacks")} value={s.outcomes.rollbacks} colorClass={s.outcomes.rollbacks > 0 ? "text-amber-500" : undefined} />
                {effKind !== "fix" && (
                  <StatCard label={t("audit.kpi.needsReview")} value={s.outcomes.needs_review} colorClass={s.outcomes.needs_review > 0 ? "text-amber-500" : undefined} />
                )}
                <StatCard label={t("audit.kpi.refused")} value={(s.commands.by_outcome.refused ?? 0) + (s.commands.by_outcome.blocked ?? 0)} colorClass={(s.commands.by_outcome.refused ?? 0) + (s.commands.by_outcome.blocked ?? 0) > 0 ? "text-amber-500" : undefined} />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="lg:col-span-2">
                  <CardHeader><h3 className="font-semibold text-sm">{t("audit.chart.series")}</h3></CardHeader>
                  <CardBody>
                    {seriesEmpty ? (
                      <p className="text-sm text-muted-foreground">{t("common.noData")}</p>
                    ) : (
                      <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <ComposedChart data={seriesData}>
                            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={(b: string) => b.slice(5)} />
                            <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                            <Tooltip />
                            <Legend />
                            <Bar dataKey="created" name={t("audit.series.created")} fill={SERIES_COLORS.created} />
                            <Bar dataKey="completed" name={t("audit.series.completed")} stackId="done" fill={SERIES_COLORS.completed} />
                            <Bar dataKey="failed" name={t("audit.series.failed")} stackId="done" fill={SERIES_COLORS.failed} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </CardBody>
                </Card>
                <Card>
                  <CardHeader><h3 className="font-semibold text-sm">{t("audit.chart.risk")}</h3></CardHeader>
                  <CardBody>
                    {riskData.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t("common.noData")}</p>
                    ) : (
                      <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie data={riskData} dataKey="value" nameKey="name" innerRadius="50%" outerRadius="80%" paddingAngle={2} label>
                              {riskData.map((r) => <Cell key={r.name} fill={RISK_COLORS[r.name] ?? "#6b7280"} />)}
                            </Pie>
                            <Tooltip />
                            <Legend />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </CardBody>
                </Card>
              </div>

              <Card>
                <CardHeader><h3 className="font-semibold text-sm">{t("audit.breakdown")}</h3></CardHeader>
                <CardBody className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {effKind !== "fix" && (
                    <StatList title={t("audit.top.requesters")} rows={s.breakdown.by_actor.requesters.map((x) => ({ label: <span className="font-mono">{x.actor}</span>, value: x.count }))} />
                  )}
                  <StatList title={t("audit.top.approvers")} rows={s.breakdown.by_actor.approvers.map((x) => ({ label: <span className="font-mono">{x.actor}</span>, value: x.count }))} />
                  <StatList title={t("audit.top.executors")} rows={s.breakdown.by_actor.executors.map((x) => ({ label: <span className="font-mono">{x.actor}</span>, value: x.count }))} />
                  {effKind !== "fix" && (
                    <StatList title={t("audit.by.changeType")} rows={sortedEntries(s.breakdown.by_change_type).map(([k, count]) => ({ label: t(`plans.changeType.${k}`), value: count }))} />
                  )}
                  {effKind !== "fix" && (
                    <StatList title={t("audit.by.actionType")} rows={sortedEntries(s.breakdown.by_action_type).map(([k, count]) => ({ label: k, value: count }))} />
                  )}
                  {effKind !== "fix" && (
                    <StatList title={t("audit.by.account")} rows={sortedEntries(s.breakdown.by_account).map(([k, count]) => ({ label: accountName(k), value: count }))} />
                  )}
                  <StatList
                    title={t("audit.timingTitle")}
                    rows={[
                      { label: t("audit.timing.approveToStart"), value: fmtSecs(s.lead_time.approve_to_start_p50_s) },
                      { label: t("audit.timing.execution"), value: fmtSecs(s.lead_time.exec_duration_p50_s) },
                    ]}
                  />
                </CardBody>
              </Card>
            </>
          )}

          {/* Decision ledger */}
          <Card>
            <CardHeader>
              <h3 className="font-semibold text-sm">{t("audit.decisions")}</h3>
              {approvalsLine && <span className="text-xs text-muted-foreground">{approvalsLine}</span>}
            </CardHeader>
            <CardBody>
              {decisionLoading ? (
                <Spinner label={t("common.loading")} />
              ) : isForbidden(decisionError) ? (
                <p className="text-sm text-muted-foreground">{t("audit.adminOnly")}</p>
              ) : decisionError ? (
                <ErrorBanner message={(decisionError as Error).message} onRetry={refetchDecisions} actionLabel={t("common.retry")} />
              ) : (
                <>
                  <DataTable columns={dcols} data={ledger.rows} rowKey={(a) => a.id} emptyMessage={t("common.noData")} />
                  {ledger.truncated && (
                    <p className="text-xs text-muted-foreground mt-2">{t("plans.limitNote").replace("{n}", String(LEDGER_LIMIT))}</p>
                  )}
                </>
              )}
            </CardBody>
          </Card>

          {/* Command ledger */}
          <Card>
            <CardHeader>
              <div>
                <h3 className="font-semibold text-sm">{t("audit.commands")}</h3>
                <p className="text-xs text-muted-foreground">{t("audit.commandsNote")}</p>
              </div>
            </CardHeader>
            <CardBody>
              {commands.isLoading ? (
                <Spinner label={t("common.loading")} />
              ) : isForbidden(commands.error) ? (
                <p className="text-sm text-muted-foreground">{t("audit.adminOnly")}</p>
              ) : commands.error ? (
                <ErrorBanner message={(commands.error as Error).message} onRetry={() => commands.refetch()} actionLabel={t("common.retry")} />
              ) : (
                <>
                  <DataTable columns={ccols} data={commands.data ?? []} rowKey={(c) => c.id} emptyMessage={t("common.noData")} />
                  {(commands.data?.length ?? 0) >= COMMAND_LIMIT && (
                    <p className="text-xs text-muted-foreground mt-2">{t("plans.limitNote").replace("{n}", String(COMMAND_LIMIT))}</p>
                  )}
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
