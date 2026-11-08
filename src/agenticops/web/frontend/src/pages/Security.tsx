import {
  ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
} from "recharts";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { QueryState } from "@/components/ui/QueryState";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import { useLocale } from "@/i18n/LocaleContext";
import {
  useAttackPaths, useSecurityFindings, useSecurityRecommendations,
  useSecuritySummary, useSecurityTrend,
} from "@/hooks/useSecurity";

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-blue-500 dark:bg-green-500",
};

const REACH_TONE: Record<string, StatusTone> = {
  reachable: "danger",
  undetermined: "warn",
  not_reachable: "ok",
};

const noItems = (d: unknown[]) => d.length === 0;

/** MVP-2.8.0 S1: every module states its own loading / failed / empty / stale — a failed request is never shown
 *  as "no findings", and one failed module never hides the others. Per-account content arrives in S3. */
export default function Security() {
  const { t } = useLocale();
  const summary = useSecuritySummary();
  const trend = useSecurityTrend(30);
  const findings = useSecurityFindings(50);
  const recs = useSecurityRecommendations("open");
  const paths = useAttackPaths();
  const all = [summary, trend, findings, recs, paths];
  const refreshing = all.some((q) => q.isFetching);
  const refreshAll = () => all.forEach((q) => void q.refetch());

  const reach = (r: string) => (
    <StatusText tone={REACH_TONE[r] ?? "neutral"} className="text-xs">
      {REACH_TONE[r] ? t(`security.reach.${r}`) : r}
    </StatusText>
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-medium">{t("nav.security")}</h1>
        <button type="button" onClick={refreshAll} disabled={refreshing}
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-60">
          <svg className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {t("security.refresh")}
        </button>
      </div>

      {/* score cards */}
      <QueryState query={summary} isEmpty={(d) => d.accounts.length === 0} emptyText={t("security.noSnapshot")}
                  onRetry={() => void summary.refetch()}>
        {(data) => (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {data.accounts.map((a) => (
              <Card key={a.account_id}>
                <CardBody>
                  <div className="text-sm text-muted-foreground">{a.account_id}</div>
                  <div className={`text-3xl font-light font-mono ${a.overall_score < 70 ? "text-primary" : ""}`}>
                    {a.overall_score.toFixed(1)}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {t("security.cardCounts").replace("{reachable}", String(a.reachable_paths)).replace("{open}", String(a.open_findings))}
                  </div>
                </CardBody>
              </Card>
            ))}
          </div>
        )}
      </QueryState>

      {/* trend + radar */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>{t("security.trend")}</CardHeader>
          <CardBody className="min-h-64">
            <QueryState query={trend} isEmpty={noItems} emptyText={t("security.noTrend")} onRetry={() => void trend.refetch()}>
              {(data) => (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={data}>
                      <XAxis dataKey="created_at" hide />
                      <YAxis domain={[0, 100]} width={30} />
                      <Tooltip />
                      <Line type="monotone" dataKey="overall_score" dot={false} strokeWidth={2} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
            </QueryState>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>{t("security.categories")}</CardHeader>
          <CardBody className="min-h-64">
            <QueryState query={summary} isEmpty={(d) => d.accounts.length === 0} emptyText={t("security.noSnapshot")}
                        onRetry={() => void summary.refetch()}>
              {(data) => (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={Object.entries(data.accounts[0].category_scores).map(([category, score]) => ({ category, score }))}>
                      <PolarGrid />
                      <PolarAngleAxis dataKey="category" />
                      <Radar dataKey="score" fillOpacity={0.4} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </QueryState>
          </CardBody>
        </Card>
      </div>

      {/* findings */}
      <Card>
        <CardHeader>{t("security.findings")}</CardHeader>
        <CardBody>
          <QueryState query={findings} isEmpty={noItems} emptyText={t("security.noFindings")} onRetry={() => void findings.refetch()}>
            {(data) => data.map((f) => (
              <div key={f.id} className="flex items-center gap-2 py-1.5 text-sm border-b border-border/50 last:border-0">
                <span className={`block w-2 h-2 rounded-full ${SEV_DOT[f.severity] ?? "bg-muted-foreground"}`} />
                <span className="flex-1 truncate">{f.title}</span>
                {f.reachability && reach(f.reachability)}
                <span className="text-xs text-muted-foreground">{f.status}</span>
              </div>
            ))}
          </QueryState>
        </CardBody>
      </Card>

      {/* recommendations */}
      <Card>
        <CardHeader>{t("security.recommendations")}</CardHeader>
        <CardBody>
          <QueryState query={recs} isEmpty={noItems} emptyText={t("security.noRecommendations")} onRetry={() => void recs.refetch()}>
            {(data) => data.map((r) => (
              <div key={r.id} className="py-1.5 text-sm border-b border-border/50 last:border-0">
                <div className="flex items-center gap-2">
                  <span className={`block w-2 h-2 rounded-full ${SEV_DOT[r.severity] ?? "bg-muted-foreground"}`} />
                  <span className="font-medium">{r.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {r.critic_verdict} · {(r.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="text-xs text-muted-foreground ml-4">{r.detail}</div>
              </div>
            ))}
          </QueryState>
        </CardBody>
      </Card>

      {/* attack paths */}
      <Card>
        <CardHeader>{t("security.paths")}</CardHeader>
        <CardBody>
          <QueryState query={paths} isEmpty={noItems} emptyText={t("security.noPaths")} onRetry={() => void paths.refetch()}>
            {(data) => data.map((p, i) => (
              <div key={i} className="flex items-center gap-2 py-1.5 text-sm font-mono border-b border-border/50 last:border-0">
                {reach(p.reachability)}
                <span className="truncate">{(p.path ?? []).join(" → ") || p.resource_id}</span>
                <span className="text-xs text-muted-foreground">:{p.port}</span>
              </div>
            ))}
          </QueryState>
        </CardBody>
      </Card>
    </div>
  );
}
