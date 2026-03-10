import React from "react";
import { cn } from "@/lib/cn";
import type { RiskLevel } from "@/api/types";

const RISK_STYLES: Record<RiskLevel, string> = {
  L0: "bg-[#383838] text-[#9b9b9b]",
  L1: "bg-blue-900/30 text-blue-400",
  L2: "bg-orange-900/30 text-orange-400",
  L3: "bg-red-900/30 text-red-400",
};

export const RiskLevelBadge = React.memo(function RiskLevelBadge({
  level,
}: {
  level: RiskLevel;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium uppercase tracking-wider",
        RISK_STYLES[level] ?? RISK_STYLES.L0,
      )}
    >
      {level}
    </span>
  );
});
