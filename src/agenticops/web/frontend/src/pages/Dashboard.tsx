import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useResourceTypeCounts } from "@/hooks/useResourceTypeCounts";
import { useExecutorStatus } from "@/hooks/useExecutorStatus";
import { useFixPlans } from "@/hooks/useFixPlans";
import { useAuditLog } from "@/hooks/useAuditLog";
import { useSchedules } from "@/hooks/useSchedules";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { formatShortDate } from "@/lib/formatDate";
import { useNavigate } from "react-router-dom";
import { useState, useMemo } from "react";
import { useDashboardTrends } from "@/hooks/useDashboardTrends";
import { useLocale } from "@/i18n/LocaleContext";

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-blue-500 dark:bg-green-500",
};

const TERMINAL_STATUSES = new Set(["executed", "rejected", "cancelled"]);

export default function Dashboard() {
  const { t } = useLocale();
  const stats = useStats();
  const anomalies = useAnomalies({ status: "open" });
  const typeCounts = useResourceTypeCounts();
  const executor = useExecutorStatus();
  const fixPlans = useFixPlans();
  const auditLog = useAuditLog({ hours: 24 });
  const schedules = useSchedules();
  const navigate = useNavigate();
  const [trendDays, setTrendDays] = useState(7);
  const trends = useDashboardTrends(trendDays);

  const resourceTypes = useMemo(() => {
    if (!typeCounts.data) return [];
    const entries = Object.entries(typeCounts.data).sort((a, b) => b[1] - a[1]);
    const max = entries[0]?.[1] ?? 1;
    return entries.map(([type, count]) => ({
      type,
      count,
      pct: (count / max) * 100,
    }));
  }, [typeCounts.data]);

  const activeFixPlans = useMemo(() => {
    if (!fixPlans.data) return [];
    return fixPlans.data.filter((fp) => !TERMINAL_STATUSES.has(fp.status));
  }, [fixPlans.data]);

  const recentActivity = useMemo(() => {
    if (!auditLog.data) return [];
    return auditLog.data.slice(0, 10);
  }, [auditLog.data]);

  const activeSchedules = useMemo(() => {
    if (!schedules.data) return [];
    return schedules.data.filter((s) => s.is_enabled);
  }, [schedules.data]);

  if (stats.isLoading) return <Spinner label={t("common.loading")} />;
  if (stats.error)
    return (
      <ErrorBanner
        message={stats.error.message}
        onRetry={() => stats.refetch()}
      />
    );

  const s = stats.data!;

  const kpis = [
    { label: t("dashboard.resources"), value: s.total_resources, hot: false },
    { label: t("dashboard.openIssues"), value: s.open_anomalies, hot: s.open_anomalies > 0 },
    { label: t("dashboard.critical"), value: s.critical_anomalies, hot: s.critical_anomalies > 0 },
    { label: t("dashboard.accounts"), value: s.total_accounts, hot: false },
  ];

  return (
    <div>
      {/* KPI Strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {kpis.map((k, i) => (
          <div
            key={k.label}
            className="bg-card border rounded-lg px-5 py-4 duo-fade"
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-1.5">
              {k.label}
            </div>
            <div className={`text-3xl font-light tracking-tight font-mono ${k.hot ? "text-primary" : ""}`}>
              {k.value}
            </div>
          </div>
        ))}
      </div>

      {/* Pipeline Bar */}
      {executor.data && (
        <div className="duo-fade flex items-center gap-4 px-1 mb-8" style={{ animationDelay: "300ms" }}>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${executor.data.running ? "bg-primary duo-pulse" : "bg-muted-foreground/30"}`} />
            <span className="text-sm text-muted-foreground">
              {t("dashboard.executor")} {executor.data.enabled ? t("common.on") : t("common.off")}
            </span>
          </div>
          <span className="w-px h-3 bg-border" />
          <span className="text-sm text-muted-foreground">
            {t("dashboard.active")} <span className="font-mono font-medium text-foreground">{executor.data.active_executions}</span>
          </span>
          <span className="w-px h-3 bg-border" />
          <span className={`text-xs px-2 py-0.5 rounded-md font-medium ${executor.data.auto_resolve ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground"}`}>
            {t("dashboard.autoResolve")} {executor.data.auto_resolve ? t("common.on") : t("common.off")}
          </span>
        </div>
      )}

      {/* Trend Strip */}
      {trends.data && (
        <div className="duo-fade mb-8" style={{ animationDelay: "340ms" }}>
          <div className="flex items-center justify-between mb-3">
            <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground">
              {t("dashboard.trends")}
            </div>
            <div className="flex gap-1">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setTrendDays(d)}
                  className={`text-[10px] px-2.5 py-1 rounded-md font-medium transition-colors ${
                    trendDays === d
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <TrendCard
              label={t("dashboard.issues")}
              value={`+${trends.data.summary.issues_opened} / -${trends.data.summary.issues_resolved}`}
              data={trends.data.issues.map((d) => d.opened ?? 0)}
              color="bg-red-500/30"
            />
            <TrendCard
              label={t("dashboard.severity")}
              value={`${trends.data.severity.reduce((s, d) => s + d.critical, 0)} crit`}
              data={trends.data.severity.map((d) => d.critical + d.high + d.medium + d.low)}
              color="bg-orange-500/30"
            />
            <TrendCard
              label={t("dashboard.resources")}
              value={`+${trends.data.summary.resource_net_change}`}
              data={trends.data.resources.map((d) => d.added)}
              color="bg-primary/30"
            />
            <TrendCard
              label={t("dashboard.mttr")}
              value={`${trends.data.summary.mttr_avg_hours}h`}
              trend={trends.data.summary.mttr_trend}
              trendGoodDirection="down"
              data={trends.data.mttr.map((d) => d.avg_hours)}
              color="bg-amber-400/30"
            />
            <TrendCard
              label={t("dashboard.fixRate")}
              value={`${trends.data.summary.fix_rate_pct}%`}
              trend={trends.data.summary.fix_rate_trend}
              trendGoodDirection="up"
              data={trends.data.fix_rate.map((d) => d.rate)}
              color="bg-green-500/30"
            />
          </div>
        </div>
      )}

      {/* Content Grid — Row 1: Recent Issues (2 cols) + Resources by Type (1 col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Issues */}
        <div className="lg:col-span-2 duo-fade" style={{ animationDelay: "380ms" }}>
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.recentIssues")}
          </div>
          {anomalies.isLoading ? (
            <Spinner />
          ) : anomalies.data && anomalies.data.length > 0 ? (
            <div className="bg-card border rounded-lg overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b">
                    <th className="w-8 pl-4 pr-1 py-2.5" />
                    <th className="px-4 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Title</th>
                    <th className="px-4 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider hidden lg:table-cell">Account</th>
                    <th className="px-4 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider hidden md:table-cell">Resource</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Detected</th>
                  </tr>
                </thead>
                <tbody>
                  {anomalies.data.slice(0, 8).map((a) => (
                    <tr
                      key={a.id}
                      className="border-b border-border/50 cursor-pointer transition-colors duration-150 hover:bg-accent"
                      onClick={() => navigate(`/app/issues/${a.id}`)}
                    >
                      <td className="pl-4 pr-1 py-2.5">
                        <span className={`block w-2 h-2 rounded-full ${SEV_DOT[a.severity] ?? "bg-muted-foreground"}`} />
                      </td>
                      <td className="px-4 py-2.5 text-sm">
                        <span className="line-clamp-1">{a.title}</span>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground hidden lg:table-cell">
                        {a.account_name ?? "-"}
                      </td>
                      <td className="px-4 py-2.5 text-xs font-mono text-muted-foreground hidden md:table-cell">
                        <span className="line-clamp-1">{a.resource_type}/{a.resource_id}</span>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground text-right whitespace-nowrap">
                        {formatShortDate(a.detected_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-16 text-center text-sm text-muted-foreground">
              {t("dashboard.noOpenIssues")}
            </div>
          )}
        </div>

        {/* Resources */}
        <div className="duo-fade" style={{ animationDelay: "460ms" }}>
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.resourcesByType")}
          </div>
          {typeCounts.isLoading ? (
            <Spinner />
          ) : resourceTypes.length > 0 ? (
            <div className="space-y-4">
              {resourceTypes.map(({ type, count, pct }) => (
                <div key={type} className="group cursor-default">
                  <div className="flex items-baseline justify-between mb-1.5">
                    <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors duration-150">
                      {type}
                    </span>
                    <span className="font-mono text-xs font-medium text-muted-foreground group-hover:text-primary transition-colors duration-150">
                      {count}
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-secondary overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary/60 group-hover:bg-primary transition-all duration-500 ease-out"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-16 text-center text-sm text-muted-foreground">
              {t("dashboard.noResources")}
            </div>
          )}
        </div>
      </div>

      {/* Content Grid — Row 2: Active Fix Plans + Recent Activity + Scheduled Jobs */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active Fix Plans */}
        <div className="duo-fade" style={{ animationDelay: "520ms" }}>
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.activeFixPlans")}
          </div>
          {fixPlans.isLoading ? (
            <Spinner />
          ) : activeFixPlans.length > 0 ? (
            <div className="space-y-2">
              {activeFixPlans.slice(0, 6).map((fp) => (
                <div
                  key={fp.id}
                  onClick={() => navigate(`/app/issues/${fp.health_issue_id}`)}
                  className="bg-card border rounded-lg px-4 py-3 cursor-pointer transition-colors duration-150 hover:bg-accent"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-foreground line-clamp-1 flex-1 mr-2">
                      {fp.title}
                    </span>
                    <RiskLevelBadge level={fp.risk_level} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-muted-foreground">
                      I#{fp.health_issue_id}
                    </span>
                    <FixPlanStatusBadge status={fp.status} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
              {t("common.noData")}
            </div>
          )}
        </div>

        {/* Recent Activity */}
        <div className="duo-fade" style={{ animationDelay: "580ms" }}>
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.recentActivity")}
          </div>
          {auditLog.isLoading ? (
            <Spinner />
          ) : recentActivity.length > 0 ? (
            <div className="bg-card border rounded-lg overflow-hidden">
              <div className="divide-y divide-border/50">
                {recentActivity.map((entry) => (
                  <div key={entry.id} className="px-4 py-2.5">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-sm font-medium text-foreground">
                        {entry.action}
                      </span>
                      <span className="text-[10px] text-muted-foreground whitespace-nowrap ml-2">
                        {formatShortDate(entry.timestamp)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs bg-secondary text-muted-foreground px-1.5 py-0.5 rounded">
                        {entry.entity_type}
                      </span>
                      {entry.details && (
                        <span className="text-xs text-muted-foreground line-clamp-1 flex-1">
                          {entry.details.length > 60
                            ? entry.details.slice(0, 60) + "..."
                            : entry.details}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
              {t("common.noData")}
            </div>
          )}
        </div>

        {/* Scheduled Jobs */}
        <div className="duo-fade" style={{ animationDelay: "640ms" }}>
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.scheduledJobs")}
          </div>
          {schedules.isLoading ? (
            <Spinner />
          ) : activeSchedules.length > 0 ? (
            <div className="space-y-2">
              {activeSchedules.slice(0, 6).map((sched) => (
                <div
                  key={sched.id}
                  onClick={() => navigate(`/app/schedules/${sched.id}`)}
                  className="bg-card border rounded-lg px-4 py-3 cursor-pointer transition-colors duration-150 hover:bg-accent"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-foreground line-clamp-1">
                      {sched.name}
                    </span>
                    <span className="text-xs font-mono text-muted-foreground ml-2 whitespace-nowrap">
                      {sched.cron_expression}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>
                      {sched.last_run_at
                        ? formatShortDate(sched.last_run_at)
                        : "Never run"}
                    </span>
                    {sched.next_run_at && (
                      <span className="text-primary">
                        Next: {formatShortDate(sched.next_run_at)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
              {t("common.noData")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TrendCard({
  label,
  value,
  trend,
  trendGoodDirection,
  data,
  color,
}: {
  label: string;
  value: string;
  trend?: "up" | "down" | "flat";
  trendGoodDirection?: "up" | "down";
  data: number[];
  color: string;
}) {
  const max = Math.max(...data, 1);
  const arrow = trend === "up" ? "\u2191" : trend === "down" ? "\u2193" : "";
  const arrowColor =
    trend && trendGoodDirection
      ? trend === trendGoodDirection
        ? "text-green-500"
        : trend === "flat"
          ? ""
          : "text-red-500"
      : "";

  return (
    <div className="bg-card border rounded-lg px-4 py-3">
      <div className="text-[10px] font-medium tracking-[0.08em] uppercase text-muted-foreground">
        {label}
      </div>
      <div className="font-mono text-lg font-light tracking-tight mt-1 mb-2">
        {value}
        {arrow && <span className={`text-xs ml-1 ${arrowColor}`}>{arrow}</span>}
      </div>
      <div className="flex items-end gap-[2px] h-5">
        {data.map((v, i) => (
          <div
            key={i}
            className={`flex-1 rounded-sm ${color}`}
            style={{ height: `${Math.max((v / max) * 100, 4)}%` }}
          />
        ))}
      </div>
    </div>
  );
}
