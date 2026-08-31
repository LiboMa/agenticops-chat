import {
  ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
} from "recharts";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
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

const REACH_BADGE: Record<string, string> = {
  reachable: "bg-red-100 text-red-700",
  undetermined: "bg-amber-100 text-amber-700",
  not_reachable: "bg-emerald-100 text-emerald-700",
};

export default function Security() {
  const { t } = useLocale();
  const summary = useSecuritySummary();
  const trend = useSecurityTrend(30);
  const findings = useSecurityFindings(50);
  const recs = useSecurityRecommendations("open");
  const paths = useAttackPaths();

  if (summary.isLoading) return <Spinner />;
  const accounts = summary.data?.accounts ?? [];
  const radarData = accounts[0]
    ? Object.entries(accounts[0].category_scores).map(([category, score]) => ({ category, score }))
    : [];

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-medium">{t("nav.security")}</h1>

      {/* score cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {accounts.map((a) => (
          <Card key={a.account_id}>
            <CardBody>
              <div className="text-sm text-muted-foreground">{a.account_id}</div>
              <div className={`text-3xl font-light font-mono ${a.overall_score < 70 ? "text-primary" : ""}`}>
                {a.overall_score.toFixed(1)}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                {a.reachable_paths} reachable · {a.open_findings} open
              </div>
            </CardBody>
          </Card>
        ))}
        {accounts.length === 0 && (
          <div className="text-sm text-muted-foreground">No security snapshot yet.</div>
        )}
      </div>

      {/* trend + radar */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>Score trend (30d)</CardHeader>
          <CardBody className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={trend.data ?? []}>
                <XAxis dataKey="created_at" hide />
                <YAxis domain={[0, 100]} width={30} />
                <Tooltip />
                <Line type="monotone" dataKey="overall_score" dot={false} strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>Category scores</CardHeader>
          <CardBody className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData}>
                <PolarGrid />
                <PolarAngleAxis dataKey="category" />
                <Radar dataKey="score" fillOpacity={0.4} />
              </RadarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      </div>

      {/* findings */}
      <Card>
        <CardHeader>Findings</CardHeader>
        <CardBody>
          {(findings.data ?? []).map((f) => (
            <div key={f.id} className="flex items-center gap-2 py-1.5 text-sm border-b border-border/50 last:border-0">
              <span className={`block w-2 h-2 rounded-full ${SEV_DOT[f.severity] ?? "bg-muted-foreground"}`} />
              <span className="flex-1 truncate">{f.title}</span>
              {f.reachability && (
                <span className={`text-xs px-1.5 py-0.5 rounded ${REACH_BADGE[f.reachability] ?? ""}`}>
                  {f.reachability}
                </span>
              )}
              <span className="text-xs text-muted-foreground">{f.status}</span>
            </div>
          ))}
          {(findings.data ?? []).length === 0 && (
            <div className="text-sm text-muted-foreground">No security findings.</div>
          )}
        </CardBody>
      </Card>

      {/* recommendations */}
      <Card>
        <CardHeader>Recommendations</CardHeader>
        <CardBody>
          {(recs.data ?? []).map((r) => (
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
          {(recs.data ?? []).length === 0 && (
            <div className="text-sm text-muted-foreground">No open recommendations.</div>
          )}
        </CardBody>
      </Card>

      {/* attack paths */}
      <Card>
        <CardHeader>Exposure paths</CardHeader>
        <CardBody>
          {(paths.data ?? []).map((p, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 text-sm font-mono border-b border-border/50 last:border-0">
              <span className={`text-xs px-1.5 py-0.5 rounded ${REACH_BADGE[p.reachability] ?? ""}`}>
                {p.reachability}
              </span>
              <span className="truncate">{(p.path ?? []).join(" → ") || p.resource_id}</span>
              <span className="text-xs text-muted-foreground">:{p.port}</span>
            </div>
          ))}
          {(paths.data ?? []).length === 0 && (
            <div className="text-sm text-muted-foreground">No exposure paths.</div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
