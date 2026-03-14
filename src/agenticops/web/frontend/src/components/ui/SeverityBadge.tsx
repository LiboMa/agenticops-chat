import React from "react";
import { cn } from "@/lib/cn";

const SEV: Record<string, { dot: string; text: string }> = {
  critical: { dot: "bg-red-500", text: "text-red-500 dark:text-red-400" },
  high: { dot: "bg-orange-500", text: "text-orange-500 dark:text-orange-400" },
  medium: { dot: "bg-amber-400", text: "text-amber-500 dark:text-amber-400" },
  low: { dot: "bg-blue-500 dark:bg-green-500", text: "text-blue-500 dark:text-green-400" },
};

interface SeverityBadgeProps {
  severity: "critical" | "high" | "medium" | "low";
}

export const SeverityBadge = React.memo(function SeverityBadge({
  severity,
}: SeverityBadgeProps) {
  const s = SEV[severity] ?? SEV.low;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-xs font-medium uppercase tracking-wider", s.text)}>
        {severity}
      </span>
    </span>
  );
});
