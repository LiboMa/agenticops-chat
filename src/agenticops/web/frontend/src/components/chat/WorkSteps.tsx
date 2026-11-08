import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import type { ToolStep } from "@/api/types";
import { formatDuration, splitWork, stepStatus, workTotals, type StepStatus, type TimelineItem } from "@/lib/workSteps";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import { toolLabelKey } from "@/lib/toolLabels";

interface Props {
  tools: ToolStep[];
  /** the reply's whole text — the narration between steps is cut out of it by offset */
  content: string;
  /** still streaming: open, steps appear as they start */
  live?: boolean;
  /** live only: one line of the model's latest thinking summary (2026-11-08) */
  thinking?: string;
}

/** The Codex-style work log above an answer (2026-11-07): what the agent did, step by step, with the model's own
 *  narration between steps. Open while it runs, one line once done («已处理 N 步 · T»); the user's toggle wins. */
export function WorkSteps({ tools, content, live, thinking }: Props) {
  const { t } = useLocale();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  if (tools.length === 0) return null;
  const { timeline } = splitWork(content, tools, { live });
  const open = userOpen ?? !!live;
  const { count, ms } = workTotals(tools);
  const header = live
    ? t("chat.work.running").replace("{n}", String(count))
    : ms === null ? t("chat.work.doneNoTime").replace("{n}", String(count))
    : t("chat.work.done").replace("{n}", String(count)).replace("{t}", formatDuration(ms, t));

  return (
    <div className="mb-3 text-[13px]">
      <button type="button" onClick={() => setUserOpen(!open)} aria-expanded={open}
              className="group inline-flex items-center gap-1.5 rounded-md py-0.5 text-muted-foreground hover:text-foreground">
        {live
          ? <span className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" />
          : <svg className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} viewBox="0 0 12 12" fill="none"
                 stroke="currentColor" strokeWidth="1.8" aria-hidden><path d="M4.5 2.5 8 6l-3.5 3.5" /></svg>}
        <span className="font-medium">{header}</span>
      </button>
      {open && (
        <ol className="relative ml-[5px] mt-1.5 space-y-1.5 border-l border-border pl-4">
          {timeline.map((item, i) => <Row key={i} item={item} />)}
          {live && thinking && (
            <li className="relative truncate text-muted-foreground/80" title={thinking}>
              <span className="absolute -left-[21.5px] top-[5px] flex h-[11px] w-[11px] items-center justify-center rounded-full bg-background">
                <span className="h-[7px] w-[7px] animate-pulse rounded-full bg-primary/50" />
              </span>
              <span className="text-muted-foreground">{t("chat.work.thinking")} · </span>{thinking}
            </li>
          )}
        </ol>
      )}
    </div>
  );
}

const STEP_TONE: Record<StepStatus, StatusTone> = { running: "info", ok: "ok", error: "danger", unknown: "neutral" };

function StatusDot({ tool }: { tool: ToolStep }) {
  const base = "absolute -left-[21.5px] top-[5px] flex h-[11px] w-[11px] items-center justify-center rounded-full bg-background";
  const status = stepStatus(tool);
  if (status === "running") {
    return <span className={base}><span className="h-[9px] w-[9px] animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" /></span>;
  }
  const tone = status === "error" ? "bg-status-danger" : status === "unknown" ? "bg-muted-foreground/40" : "bg-status-ok";
  return <span className={base}><span className={`h-[7px] w-[7px] rounded-full ${tone}`} /></span>;
}

function Row({ item }: { item: TimelineItem }) {
  const { t } = useLocale();
  const [showResult, setShowResult] = useState(false);
  if (item.kind === "text") {
    return <li className="whitespace-pre-wrap text-muted-foreground">{item.text}</li>;
  }
  const tool = item.tool;
  const key = toolLabelKey(tool.name);
  const status = stepStatus(tool);
  const failed = status === "error";
  return (
    <li className="relative">
      <StatusDot tool={tool} />
      <button type="button" disabled={!tool.result_preview} onClick={() => setShowResult((v) => !v)}
              className="flex w-full min-w-0 items-baseline gap-2 text-left disabled:cursor-default">
        <span className={`shrink-0 ${failed ? "text-red-600 dark:text-red-400" : "text-foreground"}`}>
          {key ? t(key) : <code className="font-mono text-[12px]">{tool.name}</code>}
        </span>
        <StatusText tone={STEP_TONE[status]} className="shrink-0 text-[12px]">{t(`chat.work.status.${status}`)}</StatusText>
        {tool.summary && (
          <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={tool.summary}>
            {tool.summary}
          </code>
        )}
        {typeof tool.duration_ms === "number" && tool.status !== "running" && (
          <span className="ml-auto shrink-0 tabular-nums text-[12px] text-muted-foreground">
            {formatDuration(tool.duration_ms, t)}
          </span>
        )}
      </button>
      {showResult && tool.result_preview && (
        <pre className="mt-1 whitespace-pre-wrap break-words rounded-md bg-muted px-2.5 py-1.5 font-mono text-[12px] text-muted-foreground">
          {tool.result_preview}
        </pre>
      )}
    </li>
  );
}
