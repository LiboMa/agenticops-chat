import React from "react";
import { cn } from "@/lib/cn";

const STYLES: Record<string, { dot: string; label: string }> = {
  open: { dot: "bg-red-500", label: "text-red-500 dark:text-red-400" },
  acknowledged: { dot: "bg-amber-500", label: "text-amber-600 dark:text-amber-400" },
  resolved: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
  running: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
  stopped: { dot: "bg-red-500", label: "text-red-500 dark:text-red-400" },
  available: { dot: "bg-green-500", label: "text-green-600 dark:text-green-400" },
};

const DEFAULT = { dot: "bg-muted-foreground", label: "text-muted-foreground" };

export const StatusIndicator = React.memo(function StatusIndicator({
  status,
}: {
  status: string;
}) {
  const s = STYLES[status] ?? DEFAULT;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-sm font-medium", s.label)}>{status}</span>
    </span>
  );
});
