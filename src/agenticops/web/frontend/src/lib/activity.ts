import type { PipelineEvent } from "@/api/types";

/** Event types with a sentence of their own (`activity.type.<type, dots → _>`); anything else reads generically. */
const KNOWN = new Set([
  "issue_created", "signal_gated", "issue_resource_merged", "status_changed",
  "rca_started", "rca_completed", "rca_evidence_check", "rca_critic", "rca_needs_review", "rca_human_feedback",
  "rca_disputed", "fix_approved", "execution_started", "execution_completed", "resolved", "post_resolution",
  "change_requested", "change_review_started", "policy_decision", "change_reviewed", "review_failed",
  "change_clarified", "change_approved", "change_rejected", "change_cancelled", "change_review_resolved",
  "change.requested", "change.reviewed", "change.clarified", "change.approved", "change.rejected", "change.cancelled",
  "change.execution_started", "change.completed", "change.failed", "change.rolled_back", "change.needs_review",
  "plan.approved", "plan.rejected", "plan.edited", "plan.execute_requested", "plan.execution_cancelled",
  "authz.denied", "authz.denied_shadow",
]);
const BAD = new Set(["authz.denied", "rca_disputed", "change.failed", "change.rolled_back", "change_rejected", "review_failed"]);
const WARN = new Set(["rca_needs_review", "authz.denied_shadow", "change.needs_review", "change_cancelled"]);
// The detail fields worth a sentence, first present wins (the rest stays in the raw view)
const SUMMARY_KEYS = ["reason", "verdict", "outcome", "action", "risk_level", "execution_status", "confidence"];

export interface ActivityEntry {
  ts: string;
  labelKey: string;
  labelParams: Record<string, string>;
  summary: string;
  actor: string;
  tone: "ok" | "warn" | "bad" | "info";
  count: number;
  raw: PipelineEvent[];
}

function asObject(detail: unknown): Record<string, unknown> {
  if (typeof detail === "string") {
    try { return asObject(JSON.parse(detail)); } catch { return {}; }
  }
  return detail !== null && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : {};
}

function summarize(d: Record<string, unknown>): string {
  for (const k of SUMMARY_KEYS) {
    const v = d[k];
    if (k === "confidence" && typeof v === "number") return `${Math.round(v * 100)}%`;
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

function entry(e: PipelineEvent): ActivityEntry {
  const d = asObject(e.detail);
  const type = e.event_type;
  const known = KNOWN.has(type);
  const isAuthz = type === "authz.denied" || type === "authz.denied_shadow";
  return {
    ts: e.created_at ?? "",
    labelKey: known ? `activity.type.${type.replace(/\./g, "_")}` : "activity.type.unknown",
    labelParams: isAuthz ? { rule: String(d.rule ?? ""), permission: String(d.permission ?? "") }
      : known ? {} : { type },
    summary: isAuthz ? "" : summarize(d),
    actor: e.actor || "system",
    tone: BAD.has(type) || e.status === "failed" ? "bad" : WARN.has(type) ? "warn"
      : e.status === "completed" || e.status === "succeeded" ? "ok" : "info",
    count: 1,
    raw: [e],
  };
}

/** The timeline as sentences, oldest first; a run of identical consecutive events is one entry ×N. */
export function toActivity(events: PipelineEvent[] | undefined): ActivityEntry[] {
  const sorted = [...(events ?? [])].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id - b.id);
  const out: ActivityEntry[] = [];
  for (const e of sorted) {
    const next = entry(e);
    const last = out[out.length - 1];
    if (last && last.labelKey === next.labelKey && last.summary === next.summary && last.actor === next.actor
        && JSON.stringify(last.labelParams) === JSON.stringify(next.labelParams)) {
      last.count += 1;
      last.raw.push(e);
    } else out.push(next);
  }
  return out;
}
