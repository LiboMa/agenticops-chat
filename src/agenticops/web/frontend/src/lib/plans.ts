import type { ChangeStatus, FixPlan, FixPlanStatus } from "@/api/types";

// Status sets mirror src/agenticops/models.py: VALID_CHANGE_STATUSES / CHANGE_TERMINAL_STATUSES
// and FIXPLAN_TERMINAL_STATUSES.
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

export const PLAN_TERMINAL_STATUSES: ReadonlySet<FixPlanStatus> =
  new Set<FixPlanStatus>(["executed", "failed", "rejected"]);

type PlanLink = Pick<FixPlan, "plan_kind" | "change_request_id" | "health_issue_id">;
type PlanRouteLink = Pick<FixPlan, "id" | "plan_kind" | "change_request_id">;
/** A plan's page: a fix plan its own (/app/plans/:id), a change plan its change request (MVP-2.7.0 S3). */
export function planRoute(fp: PlanRouteLink): string {
  if (fp.plan_kind === "change") {
    return fp.change_request_id != null ? `/app/changes/${fp.change_request_id}` : "/app/plans?tab=changes";
  }
  return `/app/plans/${fp.id}`;
}
/** `C#N` for a change plan, `I#N` for a fix plan, `-` when the link is missing. */
export function planRef(fp: PlanLink): string {
  if (fp.plan_kind === "change") return fp.change_request_id != null ? `C#${fp.change_request_id}` : "-";
  return fp.health_issue_id != null ? `I#${fp.health_issue_id}` : "-";
}

/** How a plan is named to people — "I#12 fix plan v2" / "C#3 implementation plan v1"; mirrors
 *  services/plan_content.plan_label, with the words from the locale. */
export function planLabel(fp: PlanLink & { plan_version?: number | null }, t: (key: string) => string): string {
  const noun = t(fp.plan_kind === "change" ? "plans.implementationPlan" : "plans.fixPlan");
  return `${planRef(fp)} ${noun} v${fp.plan_version || 1}`;
}
/** The first 8 characters of a content hash, "—" when there is none. */
export const shortHash = (h: string | null | undefined) => (h ? h.slice(0, 8) : "—");

/** The four counts PlanView's header shows ("1 step · 3 pre-checks · 3 post-checks · rollback 1"). */
export function planCounts(plan: Pick<FixPlan, "steps" | "pre_checks" | "post_checks" | "rollback_plan">) {
  const len = (v: unknown) => (Array.isArray(v) ? v.length : 0);
  const rb = plan.rollback_plan && typeof plan.rollback_plan === "object" ? plan.rollback_plan : {};
  const rollback = Array.isArray((rb as Record<string, unknown>).steps) ? len((rb as Record<string, unknown>).steps)
    : Object.keys(rb).length > 0 ? 1 : 0;
  return { steps: len(plan.steps), preChecks: len(plan.pre_checks), postChecks: len(plan.post_checks), rollback };
}

export type Period = "7d" | "30d" | "90d";
export const PERIODS: readonly Period[] = ["7d", "30d", "90d"];

export type HubTab = "fix" | "changes" | "audit";
export function hubTab(raw: string | null): HubTab {
  return raw === "changes" || raw === "audit" ? raw : "fix";
}
/** The hub tablist's keyboard: ←/→ move and wrap, Home/End jump; null for any other key (WAI-ARIA tabs pattern). */
export function nextTab<T extends string>(ids: readonly T[], current: T, key: string): T | null {
  const i = ids.indexOf(current);
  if (key === "ArrowRight") return ids[(i + 1) % ids.length];
  if (key === "ArrowLeft") return ids[(i - 1 + ids.length) % ids.length];
  if (key === "Home") return ids[0];
  if (key === "End") return ids[ids.length - 1];
  return null;
}

/** The Audit tab needs `audit.read` (admin when sign-in is on). Not offered until bootstrap says so — never flashed. */
export function auditTabVisible(boot: { auth_enabled?: boolean; user?: { is_admin?: boolean } | null } | undefined): boolean {
  if (!boot) return false;
  return !boot.auth_enabled || !!boot.user?.is_admin;
}

/** An old /app/changes or /app/audit link (bookmarks, notifications) → its hub tab, with its query kept. */
export function hubRedirect(tab: Exclude<HubTab, "fix">, search: string): string {
  const qs = new URLSearchParams(search);
  qs.delete("tab");
  const rest = qs.toString();
  return `/app/plans?tab=${tab}${rest ? `&${rest}` : ""}`;
}

/** The hub's status choices → the API's status list (draft and pending both wait for an approver). */
export const PLAN_STATUS_GROUPS = { awaiting: "draft,pending_approval", approved: "approved", executing: "executing",
  executed: "executed", failed: "failed", rejected: "rejected" } as const;
export type PlanStatusGroup = keyof typeof PLAN_STATUS_GROUPS;

export function fixPlanFilters(params: URLSearchParams): { status?: string; risk_level?: string; account_id?: number; q?: string } {
  const group = params.get("status");
  const risk = params.get("risk");
  const account = Number(params.get("account"));
  const q = params.get("q")?.trim();
  return {
    status: group && group in PLAN_STATUS_GROUPS ? PLAN_STATUS_GROUPS[group as PlanStatusGroup] : undefined,
    risk_level: risk && /^L[0-3]$/.test(risk) ? risk : undefined,
    account_id: Number.isInteger(account) && account > 0 ? account : undefined,
    q: q ? q.slice(0, 100) : undefined,
  };
}

/** The Changes tab's filters from the URL, under the API's own names — so an old /app/changes?status=planned link
 *  (bookmark, notification) still filters the list after its redirect (final review I2). */
export function changeFilters(params: URLSearchParams): { status?: ChangeStatus; account_id?: number; requested_by?: string; period?: Period } {
  const status = params.get("status");
  const account = Number(params.get("account_id"));
  const period = params.get("period");
  return {
    status: status && (CHANGE_STATUSES as readonly string[]).includes(status) ? (status as ChangeStatus) : undefined,
    account_id: Number.isInteger(account) && account > 0 ? account : undefined,
    requested_by: params.get("requested_by") || undefined,
    period: period && (PERIODS as readonly string[]).includes(period) ? (period as Period) : undefined,
  };
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
