import type { ChangeStatus, FixPlan, FixPlanStatus } from "@/api/types";

// Status sets mirror src/agenticops/models.py: VALID_CHANGE_STATUSES / CHANGE_TERMINAL_STATUSES
// and VALID_PLAN_STATUSES / FIXPLAN_TERMINAL_STATUSES.
export const CHANGE_STATUSES = ["draft", "under_review", "needs_clarification", "planned", "approved", "executing",
  "needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"] as const satisfies readonly ChangeStatus[];
// Built from the element type so a misspelt member fails to compile; widen only at the .has call for plain strings.
export const CHANGE_TERMINAL_STATUSES: ReadonlySet<ChangeStatus> =
  new Set<ChangeStatus>(["completed", "failed", "rolled_back", "rejected", "cancelled"]);
export const isTerminalChange = (s: string | undefined | null) =>
  !!s && (CHANGE_TERMINAL_STATUSES as ReadonlySet<string>).has(s);
/** The pure non-terminal -> terminal transition rule (node-testable); the timeline hook refetches once on it. */
export const becameTerminalChange = (prev: string | undefined, next: string | undefined) =>
  isTerminalChange(next) && !isTerminalChange(prev);

export const PLAN_STATUSES = ["draft", "pending_approval", "approved", "executing", "executed", "failed", "rejected"] as const satisfies readonly FixPlanStatus[];
export const PLAN_TERMINAL_STATUSES: ReadonlySet<FixPlanStatus> =
  new Set<FixPlanStatus>(["executed", "failed", "rejected"]);

type PlanLink = Pick<FixPlan, "plan_kind" | "change_request_id" | "health_issue_id">;
/** A plan's detail route: its change request or its issue; the Plans tab when the link is missing. */
export function planRoute(fp: PlanLink): string {
  if (fp.plan_kind === "change") {
    return fp.change_request_id != null ? `/app/changes/${fp.change_request_id}` : "/app/plans?tab=changes";
  }
  return fp.health_issue_id != null ? `/app/issues/${fp.health_issue_id}` : "/app/plans?tab=fix";
}
/** `C#N` for a change plan, `I#N` for a fix plan, `-` when the link is missing. */
export function planRef(fp: PlanLink): string {
  if (fp.plan_kind === "change") return fp.change_request_id != null ? `C#${fp.change_request_id}` : "-";
  return fp.health_issue_id != null ? `I#${fp.health_issue_id}` : "-";
}

export type Period = "7d" | "30d" | "90d";
export const PERIODS: readonly Period[] = ["7d", "30d", "90d"];

export type PlansTab = "fix" | "changes" | "audit";
/** The tab to show for a `?tab=` value. The Changes tab exists only while change management is enabled:
 *  "changes" (or no/unknown value) → "changes" when on, "fix" when off; "fix" and "audit" always stand. */
export function resolvePlansTab(requested: string | null, changesOn: boolean): PlansTab {
  if (requested === "fix") return "fix";
  if (requested === "audit") return "audit";
  return changesOn ? "changes" : "fix";
}

/** `?a=1&b=x` from the defined, non-empty values (numbers stringified); "" when there are none. */
export function toQuery<T extends { [K in keyof T]: string | number | undefined | null }>(params: T): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}
