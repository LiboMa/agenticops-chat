import React from "react";
import { colors } from "@/theme/colors";
import { cn } from "@/lib/cn";

interface SeverityBadgeProps {
  severity: "critical" | "high" | "medium" | "low";
}

export const SeverityBadge = React.memo(function SeverityBadge({
  severity,
}: SeverityBadgeProps) {
  const style = colors.severity[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider",
        style.bg,
        style.text,
      )}
    >
      {severity}
    </span>
  );
});
