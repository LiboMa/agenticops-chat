import { useNavigate } from "react-router-dom";
import { useAgentLogs } from "@/hooks/useAgentLogs";
import { formatShortDate } from "@/lib/formatDate";
import { useLocale } from "@/i18n/LocaleContext";

/** 最近 10 条 agent 调用流;点击行 → AgentMetrics 页。 */
export function AgentActivityFeed() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const logs = useAgentLogs({ limit: 10 }, { refetchInterval: 10_000 });

  return (
    <div className="duo-fade">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-3">
        {t("dashboard.activityFeed")}
      </div>
      {logs.data && logs.data.length > 0 ? (
        <div className="bg-card border rounded-lg overflow-hidden divide-y divide-border/50">
          {logs.data.map((e) => (
            <div
              key={e.id}
              onClick={() => navigate("/app/agent-metrics")}
              className="flex items-center gap-3 px-4 py-2 cursor-pointer hover:bg-accent transition-colors"
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${e.status === "success" ? "bg-green-500" : "bg-red-500"}`} />
              <span className="text-xs font-medium text-foreground w-16 truncate">{e.agent_name}</span>
              <span className="text-xs text-muted-foreground flex-1 truncate">{e.action}</span>
              <span className="text-[10px] font-mono text-muted-foreground/60 whitespace-nowrap">
                {(e.duration_ms / 1000).toFixed(1)}s
              </span>
              <span className="text-[10px] text-muted-foreground/60 whitespace-nowrap hidden sm:inline">
                {formatShortDate(e.created_at)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="border border-dashed rounded-lg py-12 text-center text-sm text-muted-foreground">
          {t("common.noData")}
        </div>
      )}
    </div>
  );
}
