import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useSchedules } from "@/hooks/useSchedules";
import { useFixPlans } from "@/hooks/useFixPlans";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { ServiceStatusBar } from "@/components/dashboard/ServiceStatusBar";
import { InteractionStats } from "@/components/dashboard/InteractionStats";
import { AgentActivityFeed } from "@/components/dashboard/AgentActivityFeed";
import { formatShortDate } from "@/lib/formatDate";
import { useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { useSecuritySummary } from "@/hooks/useSecurity";

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-blue-500 dark:bg-green-500",
};

const TERMINAL_STATUSES = new Set(["executed", "rejected", "cancelled"]);
const CLOSED_STATUSES = new Set(["resolved", "dismissed"]);

export default function Dashboard() {
  const { t } = useLocale();
  const stats = useStats();
  const anomalies = useAnomalies();
  const schedules = useSchedules();
  const fixPlans = useFixPlans();
  const navigate = useNavigate();
  const security = useSecuritySummary();

  const activeSchedules = useMemo(
    () => (schedules.data ?? []).filter((s) => s.is_enabled),
    [schedules.data],
  );

  const activeFixPlans = useMemo(
    () => (fixPlans.data ?? []).filter((fp) => !TERMINAL_STATUSES.has(fp.status)),
    [fixPlans.data],
  );

  if (stats.isLoading) return <Spinner label={t("common.loading")} />;
  if (stats.error)
    return <ErrorBanner message={stats.error.message} onRetry={() => stats.refetch()} />;

  const s = stats.data!;
  const kpis = [
    { label: t("dashboard.resources"), value: s.total_resources, hot: false, link: "/app/issues?view=resources" },
    { label: t("dashboard.openIssues"), value: s.open_anomalies, hot: s.open_anomalies > 0 },
    { label: t("dashboard.critical"), value: s.critical_anomalies, hot: s.critical_anomalies > 0 },
    { label: t("dashboard.accounts"), value: s.total_accounts, hot: false },
  ];

  const openIssues = (anomalies.data ?? []).filter((a) => !CLOSED_STATUSES.has(a.status));

  return (
    <div>
      {/* 1. Service status bar */}
      <ServiceStatusBar />

      {/* 2. KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {kpis.map((k, i) => (
          <div
            key={k.label}
            className={`bg-card border rounded-lg px-5 py-4 duo-fade${k.link ? " cursor-pointer hover:border-primary/50 transition-colors" : ""}`}
            style={{ animationDelay: `${i * 70}ms` }}
            onClick={k.link ? () => navigate(k.link!) : undefined}
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

      {/* 3. Interaction stats — compact single row (cost/token consolidated) */}
      <InteractionStats />

      {/* 3.5 Security highlight (MVP-2.5.0) */}
      {(() => {
        const accounts = security.data?.accounts ?? [];
        if (accounts.length === 0) return null;
        const minScore = Math.min(...accounts.map((a) => a.overall_score));
        const reachable = accounts.reduce((n, a) => n + a.reachable_paths, 0);
        const hot = minScore < 70 || reachable > 0;
        return (
          <button
            onClick={() => navigate("/app/security")}
            className="w-full text-left bg-card border border-border rounded-lg px-4 py-3 mb-6 flex items-center gap-4 hover:bg-accent/50 transition-colors"
          >
            <span className="text-sm text-muted-foreground">{t("dashboard.securityScore")}</span>
            <span className={`text-2xl font-light font-mono ${hot ? "text-primary" : ""}`}>
              {minScore.toFixed(1)}
            </span>
            <span className="text-sm text-muted-foreground ml-auto">
              {reachable} {t("dashboard.securityReachable")}
            </span>
          </button>
        );
      })()}

      {/* 4. Row 1: Open Issues (wide) + Active Fix Plans */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-2 duo-fade">
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.recentIssues")}
          </div>
          {anomalies.isLoading ? (
            <Spinner />
          ) : openIssues.length > 0 ? (
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
                  {openIssues.slice(0, 8).map((a) => (
                    <tr
                      key={a.id}
                      className="border-b border-border/50 last:border-b-0 cursor-pointer transition-colors duration-150 hover:bg-accent"
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

        {/* Active Fix Plans (restored per owner feedback) */}
        <div className="duo-fade">
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
      </div>

      {/* 5. Row 2: Agent Activity (wide) + Scheduled Jobs */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <AgentActivityFeed />
        </div>

        <div className="duo-fade">
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.scheduledJobs")}
          </div>
          {schedules.isLoading ? (
            <Spinner />
          ) : activeSchedules.length > 0 ? (
            <div className="space-y-2">
              {activeSchedules.slice(0, 4).map((sched) => (
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
