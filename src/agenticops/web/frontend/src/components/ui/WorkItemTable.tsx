import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { cn } from "@/lib/cn";
import { formatShortDate } from "@/lib/formatDate";
import type { PhaseState } from "@/lib/issuePhases";
import type { RowEmphasis, WorkItemRow } from "@/lib/workItems";

const DOT: Record<PhaseState, string> = {
  done: "bg-green-500",
  current: "bg-blue-500",
  failed: "bg-red-500",
  future: "bg-muted-foreground/30",
};

const EMPHASIS: Record<NonNullable<RowEmphasis>, string> = {
  critical: "bg-red-500/5",
  closed: "opacity-60 hover:opacity-100 focus-within:opacity-100",
};

const th = "px-4 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-[0.08em] whitespace-nowrap";

/** One table for the issue and the change list (spec §6.3). The whole row opens the work item (click, Enter); the ref and
 *  the title are real links, so a middle-click / new tab works. `rowExtra` sits on the subtitle line, always shown;
 *  `rowActions` has its own narrow last column, shown on hover / focus — an element in it marked `data-pinned` (a toast)
 *  keeps it shown. */
export function WorkItemTable({ rows, levelHeader, renderLevel, timeHeader, rowExtra, rowActions, emptyMessage, t }: {
  rows: WorkItemRow[];
  levelHeader: string;
  renderLevel: (row: WorkItemRow) => React.ReactNode;
  timeHeader: string;
  rowExtra?: (row: WorkItemRow) => React.ReactNode;
  rowActions?: (row: WorkItemRow) => React.ReactNode;
  emptyMessage: string;
  t: (k: string) => string;
}) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <div className="bg-card border border-border rounded-lg py-12 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  // The links navigate themselves; stopping the click keeps the row from navigating a second time (or, on a
  // modified click meant for a new tab, from also navigating this one).
  const stop = (e: React.MouseEvent) => e.stopPropagation();

  return (
    <div className="bg-card border border-border rounded-lg overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b">
            <th className={th}>{t("workitem.col.ref")}</th>
            <th className={th}>{t("workitem.col.title")}</th>
            <th className={th}>{t("workitem.col.status")}</th>
            <th className={th}>{t("workitem.col.wait")}</th>
            <th className={th}>{levelHeader}</th>
            <th className={th}>{t("workitem.col.account")}</th>
            <th className={th}>{timeHeader}</th>
            {rowActions && <th className="w-28" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = t(row.statusKey);
            const extra = rowExtra?.(row);
            return (
              <tr
                key={row.key}
                tabIndex={0}
                onClick={() => navigate(row.href)}
                onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) navigate(row.href); }}
                className={cn(
                  "group border-b border-border/50 last:border-b-0 cursor-pointer transition-colors hover:bg-accent focus:outline-none focus-visible:bg-accent",
                  row.emphasis && EMPHASIS[row.emphasis],
                )}
              >
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <Link to={row.href} tabIndex={-1} onClick={stop} className="font-mono text-xs text-primary hover:underline">{row.ref}</Link>
                </td>
                <td className="px-4 py-2.5 w-full max-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <Link to={row.href} tabIndex={-1} onClick={stop} className="text-sm text-foreground truncate hover:underline" title={row.title}>
                      {row.title}
                    </Link>
                    {row.recurrence > 1 && (
                      <span
                        className="shrink-0 inline-flex items-center px-1.5 py-0.5 text-xs font-semibold rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                        title={t("workitem.recurred").replace("{n}", String(row.recurrence))}
                      >
                        ×{row.recurrence}
                      </span>
                    )}
                  </div>
                  {(row.subtitle || extra) && (
                    <div className="flex items-center gap-2 min-w-0 text-xs text-muted-foreground">
                      {row.subtitle && <span className="truncate" title={row.subtitleFull ?? row.subtitle}>{row.subtitle}</span>}
                      {extra && <span className="shrink-0">{extra}</span>}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  <span className="inline-flex items-center gap-2">
                    <span className="inline-flex gap-1" aria-hidden>
                      {row.dots.map((d) => (
                        <span key={d.id} className={cn("h-2 w-2 rounded-full", DOT[d.state])} title={t(`workitem.phase.${d.id}`)} />
                      ))}
                    </span>
                    <span className="text-sm text-foreground">{status === row.statusKey ? t("workitem.sub.unknown") : status}</span>
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">{row.waitKey && t(row.waitKey)}</td>
                <td className="px-4 py-2.5 whitespace-nowrap">{renderLevel(row)}</td>
                <td className="px-4 py-2.5 text-sm text-muted-foreground whitespace-nowrap">{row.account}</td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">{row.time && formatShortDate(row.time)}</td>
                {rowActions && (
                  // React events bubble through portals (a confirm dialog), so the whole cell stops the row's click.
                  <td className="w-28 px-2 py-2" onClick={stop}>
                    <div className={cn(
                      "flex items-center justify-end gap-0.5 opacity-0 pointer-events-none transition-opacity",
                      "group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto",
                      "has-[[data-pinned]]:opacity-100",
                    )}>
                      {rowActions(row)}
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
