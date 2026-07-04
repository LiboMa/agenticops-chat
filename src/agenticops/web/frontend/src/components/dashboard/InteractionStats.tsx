import { useAgentLogSummary } from "@/hooks/useAgentLogs";
import { agentShare } from "@/lib/agentShare";
import { useLocale } from "@/i18n/LocaleContext";

const BAR_COLORS = ["bg-primary-600", "bg-primary-400", "bg-primary-300", "bg-primary-200", "bg-primary-100"];

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

/** 24h 交互统计:聚合行 + per-agent CSS 横条。 */
export function InteractionStats() {
  const { t } = useLocale();
  const summary = useAgentLogSummary(24, { refetchInterval: 10_000 });

  const per = summary.data?.per_agent ?? {};
  const rows = Object.values(per) as Array<{ calls: number; input_tokens: number; output_tokens: number; errors: number; cost_usd?: number }>;
  const totals = rows.reduce(
    (a, v) => ({
      calls: a.calls + v.calls,
      input: a.input + v.input_tokens,
      output: a.output + v.output_tokens,
      errors: a.errors + v.errors,
      cost: a.cost + (v.cost_usd ?? 0),
    }),
    { calls: 0, input: 0, output: 0, errors: 0, cost: 0 },
  );
  const shares = agentShare(per);

  return (
    <div className="mb-8 duo-fade">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
        {t("dashboard.interactions")}
      </div>
      <div className="bg-card border rounded-lg px-5 py-4">
        {summary.isError || totals.calls === 0 ? (
          <div className="text-sm text-muted-foreground">—</div>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3 text-sm">
              <span className="font-mono text-2xl font-light">{totals.calls}</span>
              <span className="text-muted-foreground">{t("dashboard.calls24h")}</span>
              <span className="font-mono text-muted-foreground">↑{fmtTokens(totals.input)} ↓{fmtTokens(totals.output)}</span>
              <span className="font-mono text-foreground">${totals.cost.toFixed(2)}</span>
              {totals.errors > 0 && (
                <span className="text-red-500 text-xs">{totals.errors} {t("dashboard.errors")}</span>
              )}
            </div>
            <div className="space-y-1.5">
              {shares.slice(0, 5).map((s, i) => (
                <div key={s.name} className="flex items-center gap-2 text-xs">
                  <span className="w-16 text-muted-foreground truncate">{s.name}</span>
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${BAR_COLORS[i] ?? "bg-primary-100"}`} style={{ width: `${s.pct}%` }} />
                  </div>
                  <span className="w-14 text-right font-mono text-muted-foreground">{s.calls} · {s.pct}%</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
