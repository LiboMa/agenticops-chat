import React from "react";
import { cn } from "@/lib/cn";
import type { FixPlanStatus } from "@/api/types";

const STATUS_STYLES: Record<FixPlanStatus, string> = {
  draft: "bg-slate-100 text-slate-600",
  pending_approval: "bg-amber-100 text-amber-700",
  approved: "bg-green-100 text-green-700",
  executing: "bg-blue-100 text-blue-700",
  executed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  rejected: "bg-red-50 text-red-600",
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
