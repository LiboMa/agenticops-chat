import React from "react";
import { cn } from "@/lib/cn";
import type { IssueStatus } from "@/api/types";

const STYLES: Record<IssueStatus, { dot: string; text: string }> = {
  open: { dot: "bg-red-500", text: "text-red-500 dark:text-red-400" },
  investigating: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  root_cause_identified: { dot: "bg-orange-500", text: "text-orange-600 dark:text-orange-400" },
  fix_planned: { dot: "bg-blue-500", text: "text-blue-600 dark:text-blue-400" },
  fix_approved: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  fix_executed: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  resolved: { dot: "bg-green-500", text: "text-green-600 dark:text-green-400" },
  acknowledged: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  dismissed: { dot: "bg-muted-foreground/50", text: "text-muted-foreground" },
};

const LABELS: Record<IssueStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  root_cause_identified: "RCA Complete",
  fix_planned: "Fix Planned",
  fix_approved: "Fix Approved",
  fix_executed: "Fix Executed",
  resolved: "Resolved",
  acknowledged: "Acknowledged",
  dismissed: "Dismissed",
};

export const IssueStatusBadge = React.memo(function IssueStatusBadge({
  status,
}: {
  status: IssueStatus;
}) {
  const s = STYLES[status] ?? STYLES.open;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-xs font-medium", s.text)}>
        {LABELS[status] ?? status}
      </span>
    </span>
  );
});
