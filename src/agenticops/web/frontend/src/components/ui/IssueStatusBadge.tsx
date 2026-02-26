import React from "react";
import { cn } from "@/lib/cn";
import type { IssueStatus } from "@/api/types";

const STATUS_STYLES: Record<IssueStatus, string> = {
  open: "bg-red-100 text-red-700",
  investigating: "bg-amber-100 text-amber-700",
  root_cause_identified: "bg-orange-100 text-orange-700",
  fix_planned: "bg-blue-100 text-blue-700",
  fix_approved: "bg-indigo-100 text-indigo-700",
  fix_executed: "bg-emerald-100 text-emerald-700",
  resolved: "bg-green-100 text-green-700",
  acknowledged: "bg-amber-100 text-amber-700",
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
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
        STATUS_STYLES[status] ?? STATUS_STYLES.open,
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
});
