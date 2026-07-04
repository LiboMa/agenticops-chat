import { useHealth } from "@/hooks/useHealth";
import { useExecutorStatus } from "@/hooks/useExecutorStatus";
import { useLocale } from "@/i18n/LocaleContext";

const DOT: Record<string, string> = {
  ok: "bg-green-500",
  warning: "bg-amber-400",
  error: "bg-red-500",
};

/** 服务状态灯带:/api/health 组件灯 + executor 状态,10s 轮询。 */
export function ServiceStatusBar() {
  const { t } = useLocale();
  const health = useHealth();
  const executor = useExecutorStatus();

  if (health.isError) {
    return (
      <div className="flex items-center gap-2 px-4 py-2.5 mb-6 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-500">
        <span className="w-2 h-2 rounded-full bg-red-500" />
        {t("dashboard.apiUnreachable")}
      </div>
    );
  }

  const checks = health.data?.checks ?? {};
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 mb-6 bg-card border rounded-lg duo-fade">
      {Object.entries(checks).map(([name, c]) => (
        <span key={name} className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <span className={`w-2 h-2 rounded-full ${DOT[c.status] ?? "bg-muted-foreground/40"}`} />
          <span className="capitalize">{name}</span>
          {typeof c.latency_ms === "number" && (
            <span className="text-xs font-mono text-muted-foreground/60">{c.latency_ms}ms</span>
          )}
        </span>
      ))}
      {executor.data && (
        <>
          <span className="w-px h-3 bg-border" />
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span className={`w-2 h-2 rounded-full ${executor.data.running ? "bg-primary duo-pulse" : "bg-muted-foreground/30"}`} />
            {t("dashboard.executor")} {executor.data.enabled ? t("common.on") : t("common.off")}
            <span className="font-mono text-foreground ml-1">{executor.data.active_executions}</span>
          </span>
        </>
      )}
      {health.data && (
        <span className="ml-auto text-[10px] font-mono text-muted-foreground/50">v{health.data.version}</span>
      )}
    </div>
  );
}
