import React from "react";
import { cn } from "@/lib/cn";
import type { FixPlanStatus } from "@/api/types";

const STYLES: Record<FixPlanStatus, { dot: string; text: string }> = {
  draft: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
  pending_approval: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  approved: { dot: "bg-green-500", text: "text-green-600 dark:text-green-400" },
  executing: { dot: "bg-blue-500 dark:bg-green-500", text: "text-blue-600 dark:text-green-400" },
  executed: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  failed: { dot: "bg-red-500", text: "text-red-500 dark:text-red-400" },
  rejected: { dot: "bg-red-400", text: "text-red-500 dark:text-red-400" },
};

const LABELS: Record<FixPlanStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending",
  approved: "Approved",
  executing: "Executing",
  executed: "Executed",
  failed: "Failed",
  rejected: "Rejected",
};

export const FixPlanStatusBadge = React.memo(function FixPlanStatusBadge({
  status,
}: {
  status: FixPlanStatus;
}) {
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-xs font-medium", s.text)}>
        {LABELS[status] ?? status}
      </span>
    </span>
  );
});
