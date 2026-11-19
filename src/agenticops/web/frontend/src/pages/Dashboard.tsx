import { useStats } from "@/hooks/useStats";
import { useHealthIssues } from "@/hooks/useHealthIssues";
import { isBlank, issueFacts } from "@/lib/issueDetail";
import { issueRow, shortId } from "@/lib/workItems";
import { waitLabel } from "@/lib/inbox";
import { CopyId } from "@/components/ui/CopyId";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { useSchedules } from "@/hooks/useSchedules";
import { useFixPlans } from "@/hooks/useFixPlans";
import { useSettings } from "@/hooks/useSettings";
import { PLAN_TERMINAL_STATUSES, planRef, planRoute } from "@/lib/plans";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { ServiceStatusBar } from "@/components/dashboard/ServiceStatusBar";
import { InteractionStats } from "@/components/dashboard/InteractionStats";
import { AgentActivityFeed } from "@/components/dashboard/AgentActivityFeed";
import { formatShortDate } from "@/lib/formatDate";
import { Link, useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { useSecuritySummary } from "@/hooks/useSecurity";
import { StatusText } from "@/components/ui/StatusText";
import { TIER_TONE, cardView } from "@/lib/security";

const CLOSED_STATUSES = new Set(["resolved", "dismissed"]);
const TH = "px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground";

export default function Dashboard() {
  const { t } = useLocale();
  const stats = useStats();
  const anomalies = useHealthIssues();
  const schedules = useSchedules();
  const fixPlans = useFixPlans();
  const settings = useSettings();
  const navigate = useNavigate();
  const security = useSecuritySummary();

  // F14: change surfaces stay hidden while the flag is not true (a settings error counts as false).
  const changesOn = settings.data?.change_management_enabled === true;

  const activeSchedules = useMemo(
    () => (schedules.data ?? []).filter((s) => s.is_enabled),
    [schedules.data],
  );

  const activePlans = useMemo(
    () =>
      (fixPlans.data ?? []).filter(
        (fp) => !PLAN_TERMINAL_STATUSES.has(fp.status) && (changesOn || fp.plan_kind === "fix"),
      ),
    [fixPlans.data, changesOn],
  );

  if (stats.isLoading) return <Spinner label={t("common.loading")} />;
  if (stats.error)
    return <ErrorBanner message={stats.error.message} onRetry={() => stats.refetch()} />;

  const s = stats.data!;
  const kpis = [
    { label: t("dashboard.resources"), value: s.total_resources, hot: false, link: "/app/resources" },
    { label: t("dashboard.openIssues"), value: s.open_anomalies, hot: s.open_anomalies > 0 },
    { label: t("dashboard.critical"), value: s.critical_anomalies, hot: s.critical_anomalies > 0 },
    { label: t("dashboard.accounts"), value: s.total_accounts, hot: false },
  ];

  const openIssues = (anomalies.data?.items ?? []).filter((a) => !CLOSED_STATUSES.has(a.status));
  const now = Date.now();

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

      {/* 3.5 Security highlight (MVP-2.5.0; one row per account since MVP-2.9.0 N20 — an account nobody could
          read says «not scored», it is never folded into a lowest score) */}
      {(() => {
        const accounts = security.data?.accounts ?? [];
        if (accounts.length === 0) return null;
        return (
          <button
            onClick={() => navigate("/app/security")}
            className="w-full text-left bg-card border border-border rounded-lg px-4 py-3 mb-6 hover:bg-accent/50 transition-colors"
          >
            <div className="text-sm text-muted-foreground">{t("dashboard.securityScore")}</div>
            <ul className="mt-1 divide-y divide-border/50">
              {accounts.map((a) => {
                const view = cardView(a);
                return (
                  <li key={a.account_name} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-1.5">
                    <span className="min-w-0 flex-1 basis-32 text-sm [overflow-wrap:anywhere]">{a.account_name}</span>
                    {view.score === null
                      ? <StatusText tone="danger" className="text-sm">{t("security.unscored")}</StatusText>
                      : <span className="text-xl font-light font-mono">{view.score}</span>}
                    {view.tier && <StatusText tone={TIER_TONE[view.tier]} className="text-xs">{t(`security.tier.${view.tier}`)}</StatusText>}
                    {view.state === "partial" && <StatusText tone="warn" className="text-xs">{t("security.partial")}</StatusText>}
                    <span className="text-sm text-muted-foreground">{a.reachable_paths} {t("dashboard.securityReachable")}</span>
                  </li>
                );
              })}
            </ul>
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
            // MVP-2.9.0 N24 (the 2.8.0 spec's R09): the title first; the resource as a short id (the whole of it in
            // the tooltip, one button copies it); then how bad, who it waits on, the account, when it was found
            <div className="bg-card border rounded-lg overflow-hidden">
              <table className="w-full table-fixed">
                <thead>
                  <tr className="border-b">
                    <th scope="col" className={`${TH} text-left`}>{t("dashboard.col.title")}</th>
                    <th scope="col" className={`${TH} w-24 text-left`}>{t("dashboard.col.severity")}</th>
                    <th scope="col" className={`${TH} hidden w-44 text-left sm:table-cell`}>{t("dashboard.col.waiting")}</th>
                    <th scope="col" className={`${TH} hidden w-32 text-left lg:table-cell`}>{t("dashboard.col.account")}</th>
                    <th scope="col" className={`${TH} hidden w-36 text-right md:table-cell`}>{t("dashboard.col.detected")}</th>
                  </tr>
                </thead>
                <tbody>
                  {openIssues.slice(0, 8).map((a) => {
                    const row = issueRow(a);
                    const type = issueFacts(a).resourceType;
                    return (
                      // the title's link stretches over the row: a click anywhere opens the issue, the keyboard reaches it
                      <tr key={a.id} className="relative border-b border-border/50 last:border-b-0 transition-colors duration-150 hover:bg-accent">
                        <td className="px-4 py-2.5">
                          <Link to={`/app/issues/${a.id}`} className="block truncate text-sm text-foreground after:absolute after:inset-0 hover:text-primary" title={a.title}>
                            {a.title}
                          </Link>
                          {!isBlank(a.resource_id) && (
                            <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                              {!isBlank(type) && <span className="shrink-0">{type}</span>}
                              <CopyId id={a.resource_id} short={shortId(a.resource_id)} />
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 align-top"><SeverityBadge severity={a.severity} /></td>
                        <td className="hidden px-4 py-2.5 align-top text-xs text-muted-foreground sm:table-cell">
                          {row.waitKey ? (
                            <>
                              <span className="block">{t(row.waitKey)}</span>
                              {row.waitSince && <span className="block">{waitLabel(row.waitSince, now, t)}</span>}
                            </>
                          ) : "—"}
                        </td>
                        <td className="hidden truncate px-4 py-2.5 align-top text-xs text-muted-foreground lg:table-cell" title={a.account_name ?? undefined}>
                          {a.account_name ?? "—"}
                        </td>
                        <td className="hidden whitespace-nowrap px-4 py-2.5 text-right align-top text-xs text-muted-foreground md:table-cell">
                          {formatShortDate(a.detected_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="border border-dashed rounded-lg py-16 text-center text-sm text-muted-foreground">
              {t("dashboard.noOpenIssues")}
            </div>
          )}
        </div>

        {/* Active Plans (restored per owner feedback) */}
        <div className="duo-fade">
          <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
            {t("dashboard.activePlans")}
          </div>
          {fixPlans.isLoading || settings.isLoading ? (
            <Spinner label={t("common.loading")} />
          ) : activePlans.length > 0 ? (
            <div className="space-y-2">
              {activePlans.slice(0, 6).map((fp) => (
                <div
                  key={fp.id}
                  onClick={() => navigate(planRoute(fp))}
                  className="bg-card border rounded-lg px-4 py-3 cursor-pointer transition-colors duration-150 hover:bg-accent"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-foreground line-clamp-1 flex-1 mr-2">
                      {fp.title}
                    </span>
                    <RiskLevelBadge level={fp.risk_level} />
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-muted-foreground">{planRef(fp)}</span>
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{t(`plans.kind.${fp.plan_kind}`)}</span>
                    </div>
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
                        : t("dashboard.neverRun")}
                    </span>
                    {sched.next_run_at && (
                      <span className="text-primary">
                        {t("dashboard.nextRun")}{formatShortDate(sched.next_run_at)}
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
