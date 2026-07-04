import { useStats } from "@/hooks/useStats";
import { useAnomalies } from "@/hooks/useAnomalies";
import { useSchedules } from "@/hooks/useSchedules";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ServiceStatusBar } from "@/components/dashboard/ServiceStatusBar";
import { InteractionStats } from "@/components/dashboard/InteractionStats";
import { AgentActivityFeed } from "@/components/dashboard/AgentActivityFeed";
import { formatShortDate } from "@/lib/formatDate";
import { useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-blue-500 dark:bg-green-500",
};

const CLOSED_STATUSES = new Set(["resolved", "dismissed"]);

export default function Dashboard() {
  const { t } = useLocale();
  const stats = useStats();
  const anomalies = useAnomalies();
  const schedules = useSchedules();
  const navigate = useNavigate();

  const activeSchedules = useMemo(
    () => (schedules.data ?? []).filter((s) => s.is_enabled),
    [schedules.data],
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

      {/* 3. Interaction stats (24h) */}
      <InteractionStats />

      {/* 4+5. Activity feed | Issues + Schedules */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentActivityFeed />

        <div className="space-y-6">
          {/* Open Issues (top 5) */}
          <div className="duo-fade">
            <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
              {t("dashboard.recentIssues")}
            </div>
            {anomalies.isLoading ? (
              <Spinner />
            ) : openIssues.length > 0 ? (
              <div className="bg-card border rounded-lg overflow-hidden">
                <table className="w-full">
                  <tbody>
                    {openIssues.slice(0, 5).map((a) => (
                      <tr
                        key={a.id}
                        className="border-b border-border/50 last:border-b-0 cursor-pointer transition-colors duration-150 hover:bg-accent"
                        onClick={() => navigate(`/app/issues/${a.id}`)}
                      >
                        <td className="pl-4 pr-1 py-2.5 w-8">
                          <span className={`block w-2 h-2 rounded-full ${SEV_DOT[a.severity] ?? "bg-muted-foreground"}`} />
                        </td>
                        <td className="px-4 py-2.5 text-sm">
                          <span className="line-clamp-1">{a.title}</span>
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
              <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
                {t("dashboard.noOpenIssues")}
              </div>
            )}
          </div>

          {/* Scheduled Jobs */}
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
    </div>
  );
}
