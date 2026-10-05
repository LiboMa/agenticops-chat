import React from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/cn";
import { formatShortDate } from "@/lib/formatDate";
import type { PhaseState } from "@/lib/issuePhases";
import type { WorkItemRow } from "@/lib/workItems";

const DOT: Record<PhaseState, string> = {
  done: "bg-green-500",
  current: "bg-blue-500",
  failed: "bg-red-500",
  future: "bg-muted-foreground/30",
};

const th = "px-4 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-[0.08em] whitespace-nowrap";

/** One table for the issue and the change list (spec §6.3): the whole row opens the work item. `rowActions` shows on
 *  hover / focus; an element in it marked `data-pinned` (a toast) keeps it shown. */
export function WorkItemTable({ rows, levelHeader, renderLevel, rowActions, emptyMessage, t }: {
  rows: WorkItemRow[];
  levelHeader: string;
  renderLevel: (row: WorkItemRow) => React.ReactNode;
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
            <th className={th}>{t("workitem.col.updated")}</th>
            {rowActions && <th className="w-0 p-0" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = t(row.statusKey);
            return (
              <tr
                key={row.key}
                tabIndex={0}
                role="link"
                onClick={() => navigate(row.href)}
                onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) navigate(row.href); }}
                className="group border-b border-border/50 last:border-b-0 cursor-pointer transition-colors hover:bg-accent focus:outline-none focus-visible:bg-accent"
              >
                <td className="px-4 py-2.5 font-mono text-xs text-primary whitespace-nowrap">{row.ref}</td>
                <td className="px-4 py-2.5 w-full max-w-0">
                  <div className="text-sm text-foreground truncate" title={row.title}>{row.title}</div>
                  {row.subtitle && (
                    <div className="text-xs text-muted-foreground truncate" title={row.subtitle}>{row.subtitle}</div>
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
                <td className="px-4 py-2.5 text-xs text-muted-foreground whitespace-nowrap">{row.updated && formatShortDate(row.updated)}</td>
                {rowActions && (
                  // A zero-width cell whose actions float over the row's right end, so they take no column space.
                  // React events bubble through portals (a confirm dialog), so the whole cell stops the row's click.
                  <td className="relative w-0 p-0" onClick={(e) => e.stopPropagation()}>
                    <div className={cn(
                      "absolute right-3 top-1/2 -translate-y-1/2 z-10 flex items-center gap-1 whitespace-nowrap empty:hidden",
                      "bg-card/95 backdrop-blur-sm border border-border rounded-lg shadow-md px-1.5 py-1",
                      "opacity-0 pointer-events-none transition-opacity",
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
