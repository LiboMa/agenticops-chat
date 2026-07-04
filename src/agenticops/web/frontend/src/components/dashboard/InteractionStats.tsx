import { useAgentLogSummary } from "@/hooks/useAgentLogs";
import { agentShare } from "@/lib/agentShare";
import { useLocale } from "@/i18n/LocaleContext";

const SEG_COLORS = ["bg-primary-600", "bg-primary-400", "bg-primary-300", "bg-primary-200", "bg-primary-100"];

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

/** 24h 交互统计 — 紧凑单行:聚合数字 + 分段占比条 + 前三 agent(Cost/Token 整合)。 */
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

  if (summary.isError || totals.calls === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 mb-8 bg-card border rounded-lg duo-fade text-sm">
      <span className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground">
        {t("dashboard.interactions")}
      </span>
      <span className="font-mono text-foreground">{totals.calls} {t("dashboard.calls24h")}</span>
      <span className="font-mono text-muted-foreground text-xs">↑{fmtTokens(totals.input)} ↓{fmtTokens(totals.output)} · ${totals.cost.toFixed(2)}</span>
      {totals.errors > 0 && (
        <span className="text-red-500 text-xs">{totals.errors} {t("dashboard.errors")}</span>
      )}
      {/* 分段堆叠占比条 */}
      <div className="flex-1 min-w-[120px] h-2 rounded-full overflow-hidden flex bg-muted">
        {shares.slice(0, 5).map((s, i) => (
          <div key={s.name} className={SEG_COLORS[i] ?? "bg-primary-100"} style={{ width: `${s.pct}%` }} title={`${s.name} ${s.pct}%`} />
        ))}
      </div>
      <span className="text-xs text-muted-foreground whitespace-nowrap">
        {shares.slice(0, 3).map((s) => `${s.name} ${s.pct}%`).join(" · ")}
      </span>
    </div>
  );
}
