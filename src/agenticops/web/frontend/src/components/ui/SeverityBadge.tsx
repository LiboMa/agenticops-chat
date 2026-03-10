import React from "react";
import { cn } from "@/lib/cn";

interface SeverityBadgeProps {
  severity: "critical" | "high" | "medium" | "low";
}

const DOT_COLORS: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-yellow-500",
  low: "bg-[#9b9b9b]",
};

export const SeverityBadge = React.memo(function SeverityBadge({
  severity,
}: SeverityBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#9b9b9b]">
      <span className={cn("w-2 h-2 rounded-full", DOT_COLORS[severity] ?? "bg-[#9b9b9b]")} />
      {severity}
    </span>
  );
});
