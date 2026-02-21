import { memo } from "react";
import { cn } from "@/lib/cn";
import type { NodeStatus } from "../types";

const STATUS_COLOR: Record<NodeStatus, string> = {
  healthy: "bg-green-500",
  warning: "bg-yellow-400",
  error: "bg-red-500 animate-pulse",
  unknown: "bg-gray-400",
};

interface StatusBadgeProps {
  status?: NodeStatus;
}

function StatusBadgeInner({ status }: StatusBadgeProps) {
  if (!status) return null;
  return (
    <span
      className={cn(
        "absolute -top-1 -right-1 w-3 h-3 rounded-full border-2 border-white",
        STATUS_COLOR[status],
      )}
    />
  );
}

export const StatusBadge = memo(StatusBadgeInner);
