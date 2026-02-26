import React from "react";
import { cn } from "@/lib/cn";
import type { RiskLevel } from "@/api/types";

const RISK_STYLES: Record<RiskLevel, string> = {
  L0: "bg-slate-100 text-slate-600",
  L1: "bg-blue-100 text-blue-700",
  L2: "bg-orange-100 text-orange-700",
  L3: "bg-red-100 text-red-700",
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
