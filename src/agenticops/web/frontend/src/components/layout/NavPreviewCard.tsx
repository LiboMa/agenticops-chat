import { useQueryClient } from "@tanstack/react-query";
import { useStats } from "@/hooks/useStats";
import { useLocale } from "@/i18n/LocaleContext";
import type { ChatSession } from "@/api/types";

/** hover 预览卡片:页面名 + 一行实时摘要。数据只读现有缓存,绝不发新请求。 */
export function NavPreviewCard({ id, labelKey }: { id: string; labelKey: string }) {
  const { t } = useLocale();
  const qc = useQueryClient();
  const stats = useStats(); // sidebar 本就订阅(badge),非新请求

  let summary = "";
  if (id === "dashboard" && stats.data) {
    summary = `${stats.data.total_resources} resources · ${stats.data.total_accounts} accounts`;
  } else if (id === "issues" && stats.data) {
    summary = `${stats.data.open_anomalies} open · ${stats.data.critical_anomalies} critical`;
  } else if (id === "chat") {
    const sessions = qc.getQueryData<ChatSession[]>(["chat-sessions"]);
    if (sessions) summary = `${sessions.length} sessions`;
  } else if (id === "schedules") {
    const rows = qc.getQueryData<unknown[]>(["schedules"]);
    if (Array.isArray(rows)) summary = `${rows.length} jobs`;
  } else if (id === "reports") {
    const rows = qc.getQueryData<unknown[]>(["reports"]);
    if (Array.isArray(rows)) summary = `${rows.length} reports`;
  } else if (id === "skills") {
    const rows = qc.getQueryData<unknown[]>(["skills"]);
    if (Array.isArray(rows)) summary = `${rows.length} skills`;
  }

  return (
    <div className="w-44">
      <div className="text-xs font-medium text-foreground">{t(labelKey)}</div>
      {summary && <div className="text-[11px] text-muted-foreground mt-0.5">{summary}</div>}
    </div>
  );
}
