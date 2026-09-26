import type { ChangeStatus, FixPlanStatus } from "@/api/types";

// Status sets mirror src/agenticops/models.py: VALID_CHANGE_STATUSES / CHANGE_TERMINAL_STATUSES
// and VALID_PLAN_STATUSES / FIXPLAN_TERMINAL_STATUSES.
export const CHANGE_STATUSES = ["draft", "under_review", "needs_clarification", "planned", "approved", "executing",
  "needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"] as const satisfies readonly ChangeStatus[];
export const CHANGE_TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "rolled_back", "rejected", "cancelled"]);
export const isTerminalChange = (s: string | undefined | null) => !!s && CHANGE_TERMINAL_STATUSES.has(s);

export const PLAN_STATUSES = ["draft", "pending_approval", "approved", "executing", "executed", "failed", "rejected"] as const satisfies readonly FixPlanStatus[];
export const PLAN_TERMINAL_STATUSES: ReadonlySet<string> = new Set(["executed", "failed", "rejected"]);

export type Period = "7d" | "30d" | "90d";
export const PERIODS: readonly Period[] = ["7d", "30d", "90d"];

/** `?a=1&b=x` from the defined, non-empty values (numbers stringified); "" when there are none. */
export function toQuery(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}
