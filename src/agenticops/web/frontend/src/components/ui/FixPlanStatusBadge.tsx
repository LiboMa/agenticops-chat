import React from "react";
import { cn } from "@/lib/cn";
import type { FixPlanStatus } from "@/api/types";

const STATUS_STYLES: Record<FixPlanStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  pending_approval: "bg-yellow-100 text-yellow-800",
  approved: "bg-green-100 text-green-800",
  executing: "bg-blue-100 text-blue-800",
  executed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
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
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold",
        STATUS_STYLES[status] ?? STATUS_STYLES.draft,
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
});
