import React from "react";
import { cn } from "@/lib/cn";
import { useLocale } from "@/i18n/LocaleContext";
import type { ChangeStatus } from "@/api/types";

const STYLES: Record<ChangeStatus, { dot: string; text: string }> = {
  draft: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
  under_review: { dot: "bg-blue-500 animate-pulse", text: "text-blue-600 dark:text-blue-400" },
  needs_clarification: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  planned: { dot: "bg-violet-500", text: "text-violet-600 dark:text-violet-400" },
  approved: { dot: "bg-green-500", text: "text-green-600 dark:text-green-400" },
  // Same state, same colour across badges (Task 1 F1): FixPlanStatusBadge's executing tones + the brief's pulse.
  executing: { dot: "bg-blue-500 dark:bg-green-500 animate-pulse", text: "text-blue-600 dark:text-green-400" },
  needs_review: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  completed: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  failed: { dot: "bg-red-500", text: "text-red-500 dark:text-red-400" },
  rolled_back: { dot: "bg-red-400", text: "text-red-500 dark:text-red-400" },
  rejected: { dot: "bg-red-400", text: "text-red-500 dark:text-red-400" },
  cancelled: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
};

export const ChangeStatusBadge = React.memo(function ChangeStatusBadge({ status }: { status: ChangeStatus }) {
  const { t } = useLocale();
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      <span className={cn("text-xs font-medium", s.text)}>{t(`changes.status.${status}`)}</span>
    </span>
  );
});
