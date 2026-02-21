import { memo } from "react";
import { cn } from "@/lib/cn";
import type { NodeStatus } from "../types";

const STATUS_COLOR: Record<NodeStatus, string> = {
  healthy: "bg-green-500 ring-2 ring-green-500/30",
  warning: "bg-yellow-400 ring-2 ring-yellow-400/30",
  error: "bg-red-500 animate-pulse ring-2 ring-red-500/30",
  unknown: "bg-gray-400 ring-2 ring-gray-400/30",
};

interface StatusBadgeProps {
  status?: NodeStatus;
}

function StatusBadgeInner({ status }: StatusBadgeProps) {
  if (!status) return null;
  return (
    <span
      className={cn(
        "absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full border-2 border-white",
        STATUS_COLOR[status],
      )}
    />
  );
}

export const StatusBadge = memo(StatusBadgeInner);
