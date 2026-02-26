import React from "react";
import { cn } from "@/lib/cn";

const STATUS_STYLES: Record<string, { dot: string; label: string }> = {
  open: { dot: "bg-red-500", label: "text-red-700" },
  acknowledged: { dot: "bg-amber-500", label: "text-amber-700" },
  resolved: { dot: "bg-green-500", label: "text-green-700" },
  running: { dot: "bg-green-500", label: "text-green-700" },
  stopped: { dot: "bg-red-500", label: "text-red-700" },
  available: { dot: "bg-green-500", label: "text-green-700" },
};

const DEFAULT_STYLE = { dot: "bg-slate-400", label: "text-slate-500" };

interface StatusIndicatorProps {
  status: string;
}

export const StatusIndicator = React.memo(function StatusIndicator({
  status,
}: StatusIndicatorProps) {
  const style = STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", style.dot)} />
      <span className={cn("text-sm font-medium", style.label)}>{status}</span>
    </span>
  );
});
