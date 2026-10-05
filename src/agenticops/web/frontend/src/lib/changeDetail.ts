import type {
  ChangeExternalRef, ChangeRequest, ChangeStatus, ChangeStepsDiff, ChangeTarget, ChangeTimelineEntry, FixExecution,
  FixPlan, PipelineEvent,
} from "@/api/types";
import { formatShortDate } from "@/lib/formatDate";
import { executionStatusLabel } from "@/lib/issueDetail";

const norm = (s: string) => s.trim().toLowerCase();

/**
 * True when `hint` (a raw target_hints string) resolves to one of the
 * change's structured targets — by resource_id or by the target's own hint.
 * Comparison is trim + case-insensitive; a target with no hint never throws.
 */
export function isHintResolved(hint: string, targets: Pick<ChangeTarget, "resource_id" | "hint">[]): boolean {
  const h = norm(hint);
  return targets.some((t) => norm(t.resource_id) === h || (t.hint != null && norm(t.hint) === h));
}

// Object detail values are JSON-stringified so PipelineTimeline (which renders
// each value with String()) shows structured payloads instead of "[object Object]".
function stringifyObjectValues(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = v !== null && typeof v === "object" ? JSON.stringify(v) : v;
  }
  return out;
}

function normalizeDetail(detail: unknown): Record<string, unknown> | null {
  if (detail === null || detail === undefined) return null;
  if (typeof detail === "object" && !Array.isArray(detail)) {
    return stringifyObjectValues(detail as Record<string, unknown>);
  }
  // A legacy string or an array is wrapped under a single `detail` key.
  return stringifyObjectValues({ detail });
}

/**
 * Adapt the backend's merged change timeline (events + audit rows) into the
 * PipelineEvent shape the Task-2 PipelineTimeline component consumes. The row
 * index becomes the id; missing fields fall back to component-safe defaults.
 */
export function toPipelineEvents(entries: ChangeTimelineEntry[]): PipelineEvent[] {
  return entries.map((e, i) => ({
    id: i,
    event_type: e.type,
    stage: e.stage ?? "",
    status: e.status ?? "",
    detail: normalizeDetail(e.detail),
    actor: e.actor ?? "system",
    duration_ms: null,
    created_at: e.ts ?? "",
    trace_id: null,
  }));
}

/**
 * Extract the display-relevant fields from a policy_decision blob, tolerating
 * missing keys and non-string junk. `escalated_from`/`effective_risk_level`
 * become null when absent or empty; `reasons` keeps only strings, minus any
 * already `shown` (the backend copies policy reasons into review_reasons).
 */
export function policySummary(
  pd: Record<string, unknown> | null | undefined,
  shown: readonly string[] = [],
): { reasons: string[]; escalatedFrom: string | null; effectiveRisk: string | null } {
  const rr = pd?.reasons;
  const reasons = Array.isArray(rr)
    ? rr.filter((r): r is string => typeof r === "string" && !shown.includes(r))
    : [];
  const esc = pd?.escalated_from;
  const escalatedFrom = typeof esc === "string" && esc !== "" ? esc : null;
  const eff = pd?.effective_risk_level;
  const effectiveRisk = typeof eff === "string" && eff !== "" ? eff : null;
  return { reasons, escalatedFrom, effectiveRisk };
}

/** What must happen next (a `changes.todo.*` key) and the header's primary button, by status; completed → none;
 *  a change closed without completing → copy it as a new request. */
export type ChangeNextAction = "review" | "clarify" | "approve" | "execute" | "accept" | "copy";
const NEXT: Partial<Record<ChangeStatus, [todo: string, action: ChangeNextAction | null]>> = {
  draft: ["startReview", "review"],
  under_review: ["review", null],
  needs_clarification: ["clarify", "clarify"],
  planned: ["approve", "approve"],
  approved: ["notQueued", "execute"], // approving runs it; still approved = the run was not queued → retry
  executing: ["executing", null],
  needs_review: ["accept", "accept"],
  failed: ["copyAsNew", "copy"],
  rolled_back: ["copyAsNew", "copy"],
  rejected: ["copyAsNew", "copy"],
  cancelled: ["copyAsNew", "copy"],
};

export interface ChangeHeadline {
  reason: string | null;
  todo: string | null;
  action: ChangeNextAction | null;
}

/**
 * The one line at the top of ChangeDetail (spec §3.E.4): status · reason · to-do · primary action. Waiting for
 * acceptance, the reason is needs_review_reason — the verification reason the run itself carries, which is what
 * IssueDetail shows for a fix — falling back to that run's own on a row from before the column.
 */
export function changeHeadline(
  cr: Pick<ChangeRequest, "status" | "needs_review_reason" | "review_reasons" | "rejection_reason">,
  latest: FixExecution | null,
): ChangeHeadline {
  const [todo, action] = NEXT[cr.status] ?? [null, null];
  let reason: string | null = null;
  if (cr.status === "needs_review") {
    reason = cr.needs_review_reason || latest?.verification_reason || null;
  } else if (cr.status === "needs_clarification") {
    reason = cr.review_reasons.join(" · ") || null;
  } else if (cr.status === "rejected" || cr.status === "cancelled") {
    reason = cr.rejection_reason || null;
  } else if (cr.status === "failed" || cr.status === "rolled_back") {
    reason = latest?.acceptance_note || latest?.verification_reason || latest?.error_message || null;
  }
  return { reason, todo, action };
}

export type PlanStepMark = { kind: "added" } | { kind: "modified"; proposed: string };
export interface PlanStepMarks {
  byPlanStep: Map<number, PlanStepMark>; // 1-based plan step → how it differs from the request
  removed: ChangeStepsDiff["removed"]; // requested steps the plan dropped
  added: number;
  modified: number;
  unchanged: number;
  identical: boolean;
}

/** steps_diff folded onto the plan's own steps; null when the request brought no steps of its own. */
export function planStepMarks(diff: ChangeStepsDiff | null | undefined): PlanStepMarks | null {
  if (!diff) return null;
  const byPlanStep = new Map<number, PlanStepMark>();
  for (const a of diff.added ?? []) byPlanStep.set(a.plan_step, { kind: "added" });
  for (const m of diff.modified ?? []) byPlanStep.set(m.plan_step, { kind: "modified", proposed: m.proposed });
  const removed = diff.removed ?? [];
  const [added, modified] = [(diff.added ?? []).length, (diff.modified ?? []).length];
  return { byPlanStep, removed, added, modified, unchanged: diff.unchanged ?? 0,
           identical: added + modified + removed.length === 0 };
}

/** The external ticket as a link: "<system> <ticket_id>", linked only to an http(s) URL. */
export function externalRefLink(
  ref: ChangeExternalRef | null | undefined,
): { label: string; url: string | null; requestedBy: string | null } | null {
  if (!ref) return null;
  const url = ref.url && /^https?:\/\//i.test(ref.url) ? ref.url : null;
  return { label: `${ref.system} ${ref.ticket_id}`, url, requestedBy: ref.requested_by || null };
}

const TERMINAL_PLAN: readonly string[] = ["executed", "failed", "rejected"];

/** The plan an approve acts on — the backend's active_plan_for: the newest (plans come created_at desc) not
 *  executed / failed / rejected; else the newest, for display only; null with no plan. */
export function activeChangePlan(plans: FixPlan[]): FixPlan | null {
  return plans.find((p) => !TERMINAL_PLAN.includes(p.status)) ?? plans[0] ?? null;
}

/* -- ChangeDetail's labels and one-line summaries (components/change render them) -- */

type T = (key: string) => string;
// The values the backend writes: change_service.REVIEW_VERDICTS, policy_engine.VALID_ACTIONS, ChangeRequest.source
const REVIEW_VERDICTS = ["approved_for_planning", "needs_clarification", "rejected"];
const POLICY_ACTIONS = ["auto_approve", "require_human", "require_itsm_change", "block", "escalate"];
const SOURCES = ["chat", "web", "cli", "im", "webhook", "api"];
const label = (known: readonly string[], prefix: string) => (v: string | null | undefined, t: T): string | null =>
  v ? (known.includes(v) ? t(`${prefix}.${v}`) : v) : null;

/** An enum the backend wrote, in words; a value this page does not know stays as it came, none is null. */
export const verdictLabel = label(REVIEW_VERDICTS, "changes.reviewVerdict");
export const policyActionLabel = label(POLICY_ACTIONS, "changes.policyAction");
export const sourceLabel = label(SOURCES, "changes.source");

// Join the present, non-empty parts with " · " (no dangling separators).
const joinDot = (parts: Array<string | null | undefined | false>): string =>
  parts.filter((x): x is string => typeof x === "string" && x.length > 0).join(" · ");

/** The requester's target hints no structured target matched: shown amber, and counted as targets. */
export function unresolvedHints(cr: Pick<ChangeRequest, "target_hints" | "target_resources">): string[] {
  return cr.target_hints.filter((h) => !isHintResolved(h, cr.target_resources));
}

/** ①'s collapsed line: who asked, when, and for how many targets. */
export function requestSummary(
  cr: Pick<ChangeRequest, "requested_by" | "requested_at" | "created_at" | "target_hints" | "target_resources">, t: T,
): string {
  const n = cr.target_resources.length + unresolvedHints(cr).length;
  return t("workitem.summary.request")
    .replace("{by}", cr.requested_by)
    .replace("{at}", formatShortDate(cr.requested_at ?? cr.created_at))
    .replace("{n}", String(n));
}

/** ②'s collapsed line: verdict · risk · action — the template's "·" segments, one with no value dropped. */
export function reviewSummary(cr: Pick<ChangeRequest, "review_verdict" | "risk_level" | "action_type">, t: T): string | null {
  const parts: Record<string, string | null> = {
    verdict: verdictLabel(cr.review_verdict, t), risk: cr.risk_level, action: cr.action_type,
  };
  const line = t("workitem.summary.review")
    .split("·")
    .map((seg) => seg.replace(/\{(\w+)\}/g, (_, k: string) => parts[k] ?? "").trim())
    .filter(Boolean)
    .join(" · ");
  return line || null;
}

/** A run's one-line label: its number, then its verdict, else its status in words. */
export function runLabel(ex: Pick<FixExecution, "id" | "status" | "verification_status">, t: T): string {
  return joinDot([t("issues.executionN").replace("{n}", String(ex.id)),
    ex.verification_status ? t(`verification.${ex.verification_status}`) : executionStatusLabel(ex.status, t)]);
}

/** ④'s collapsed line: who approved it, then the latest run and its verdict. */
export function runSummary(
  cr: Pick<ChangeRequest, "approved_by">, latestRun: Pick<FixExecution, "id" | "status" | "verification_status"> | null, t: T,
): string | null {
  return joinDot([cr.approved_by && `${t("plans.approvedBy")}: ${cr.approved_by}`, latestRun && runLabel(latestRun, t)]) || null;
}
