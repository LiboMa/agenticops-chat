import React from "react";
import { cn } from "@/lib/cn";
import type { RiskLevel } from "@/api/types";

const STYLES: Record<RiskLevel, string> = {
  L0: "bg-secondary text-secondary-foreground",
  L1: "bg-primary/10 text-primary",
  L2: "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400",
  L3: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400",
};

export const RiskLevelBadge = React.memo(function RiskLevelBadge({
  level,
}: {
  level: RiskLevel;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium font-mono tracking-wider",
        STYLES[level] ?? STYLES.L0,
      )}
    >
      {level}
    </span>
  );
});
