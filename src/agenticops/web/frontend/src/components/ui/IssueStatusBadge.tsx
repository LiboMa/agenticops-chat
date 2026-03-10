import React from "react";
import { cn } from "@/lib/cn";
import type { IssueStatus } from "@/api/types";

const DOT_COLORS: Record<IssueStatus, string> = {
  open: "bg-red-500",
  investigating: "bg-amber-500",
  root_cause_identified: "bg-orange-500",
  fix_planned: "bg-blue-500",
  fix_approved: "bg-indigo-500",
  fix_executed: "bg-emerald-500",
  resolved: "bg-green-500",
  acknowledged: "bg-amber-400",
};

const STATUS_LABELS: Record<IssueStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  root_cause_identified: "RCA Complete",
  fix_planned: "Fix Planned",
  fix_approved: "Fix Approved",
  fix_executed: "Fix Executed",
  resolved: "Resolved",
  acknowledged: "Acknowledged",
};

export const IssueStatusBadge = React.memo(function IssueStatusBadge({
  status,
}: {
  status: IssueStatus;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#9b9b9b]">
      <span className={cn("w-2 h-2 rounded-full", DOT_COLORS[status] ?? "bg-[#666]")} />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
});
