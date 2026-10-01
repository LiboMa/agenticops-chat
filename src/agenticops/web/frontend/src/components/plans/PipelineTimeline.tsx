import { useState } from "react";
import { formatFullDate } from "@/lib/formatDate";
import { useLocale } from "@/i18n/LocaleContext";
import type { PipelineEvent } from "@/api/types";

/* ================================================================== */
/*  Pipeline Timeline                                                  */
/* ================================================================== */

const STAGE_COLORS: Record<string, string> = {
  detection: "bg-blue-500",
  rca: "bg-amber-500",
  planning: "bg-violet-500",
  approval: "bg-emerald-500",
  execution: "bg-orange-500",
  resolution: "bg-green-600",
  notification: "bg-muted-foreground/40",
  audit: "bg-fuchsia-500",
  review: "bg-cyan-500",
  intake: "bg-blue-500",
};

const STATUS_ICONS: Record<string, string> = {
  completed: "\u2713",
  started: "\u25B6",
  failed: "\u2717",
  skipped: "\u2013",
};

/** Change-event statuses that read as a failure, or as waiting on a human. Issue pipeline events only use
 *  started/completed/failed/skipped, so IssueDetail renders exactly as before. */
const BAD_STATUSES = new Set(["failed", "rejected", "cancelled", "rolled_back", "block"]);
const WARN_STATUSES = new Set(["needs_review", "needs_clarification"]);

export function PipelineTimeline({ events }: { events: PipelineEvent[] }) {
  return (
    <div className="relative">
      <div className="absolute left-[15px] top-2 bottom-2 w-0.5 bg-muted" />
      <div className="space-y-3">
        {events.map((ev, i) => {
          const color = STAGE_COLORS[ev.stage] || "bg-muted-foreground/40";
          const icon = STATUS_ICONS[ev.status] || "\u2022";
          const isFailed = BAD_STATUSES.has(ev.status);
          return (
            <div key={ev.id ?? i} className="relative flex items-start gap-3 pl-0">
              <div
                className={`relative z-10 flex-shrink-0 w-[31px] h-[31px] rounded-full flex items-center justify-center text-white text-xs font-bold ${color} ${isFailed ? "ring-2 ring-red-300" : ""}`}
              >
                {icon}
              </div>
              <div className="flex-1 min-w-0 pb-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-foreground">
                    {ev.event_type.replace(/_/g, " ")}
                  </span>
                  {ev.status && (
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                        isFailed
                          ? "bg-red-500/20 text-red-400"
                          : WARN_STATUSES.has(ev.status)
                            ? "bg-amber-500/20 text-amber-500"
                            : ev.status === "started"
                              ? "bg-blue-500/20 text-blue-400"
                              : ev.status === "skipped"
                                ? "bg-secondary text-muted-foreground"
                                : "bg-green-500/20 text-green-400"
                      }`}
                    >
                      {ev.status}
                    </span>
                  )}
                  {ev.duration_ms != null && ev.duration_ms > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {ev.duration_ms >= 1000
                        ? `${(ev.duration_ms / 1000).toFixed(1)}s`
                        : `${ev.duration_ms}ms`}
                    </span>
                  )}
                  {ev.trace_id && (
                    <span className="text-[10px] font-mono text-primary">
                      {ev.trace_id}
                    </span>
                  )}
                </div>
                {ev.detail && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {Object.entries(ev.detail).map(([k, v]) =>
                      v != null ? <DetailChip key={k} name={k} value={v} /> : null,
                    )}
                  </div>
                )}
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {ev.actor !== "system" && <span className="mr-2">{ev.actor}</span>}
                  {formatFullDate(ev.created_at)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const CHIP_CLIP = 80;

/** One detail value: shown whole when short; a long one opens to its full text instead of being cut off. */
function DetailChip({ name, value }: { name: string; value: unknown }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  const chip = "px-1.5 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground font-mono";
  if (text.length <= CHIP_CLIP) return <span className={`inline-flex items-center ${chip}`}>{name}: {text}</span>;
  return (
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
            title={open ? t("issues.collapse") : t("issues.expand")}
            className={`${chip} text-left hover:bg-accent ${open ? "w-full whitespace-pre-wrap break-all" : ""}`}>
      {name}: {open ? text : `${text.slice(0, CHIP_CLIP)}…`}
    </button>
  );
}
