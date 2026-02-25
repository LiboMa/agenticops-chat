import React from "react";
import { cn } from "@/lib/cn";
import type { RiskLevel } from "@/api/types";

const RISK_STYLES: Record<RiskLevel, string> = {
  L0: "bg-gray-100 text-gray-700",
  L1: "bg-blue-100 text-blue-800",
  L2: "bg-orange-100 text-orange-800",
  L3: "bg-red-100 text-red-800",
};

export const RiskLevelBadge = React.memo(function RiskLevelBadge({
  level,
}: {
  level: RiskLevel;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider",
        RISK_STYLES[level] ?? RISK_STYLES.L0,
      )}
    >
      {level}
    </span>
  );
});
