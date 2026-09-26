import type { ChangeTarget, ChangeTimelineEntry, PipelineEvent } from "@/api/types";

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
