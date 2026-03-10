import React from "react";
import { cn } from "@/lib/cn";
import type { FixPlanStatus } from "@/api/types";

const STATUS_STYLES: Record<FixPlanStatus, string> = {
  draft: "bg-[#383838] text-[#9b9b9b]",
  pending_approval: "bg-amber-900/30 text-amber-400",
  approved: "bg-green-900/30 text-green-400",
  executing: "bg-blue-900/30 text-blue-400",
  executed: "bg-emerald-900/30 text-emerald-400",
  failed: "bg-red-900/30 text-red-400",
  rejected: "bg-red-50 text-red-400",
};

const STATUS_LABELS: Record<FixPlanStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending Approval",
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
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
        STATUS_STYLES[status] ?? STATUS_STYLES.draft,
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
});
