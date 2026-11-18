import type { AttentionItem } from "@/lib/attention";

/** Which page a waiting item gets. The table is tests/fixtures/attention_brief_kinds.json, shared with the server:
 *  pytest proves the server can send exactly those rows, vitest that each has this brief. */
export const BRIEF_KINDS = ["approve", "accept", "resolve", "confirm", "rerun", "generate", "replan", "failed",
  "not_started", "start_review", "clarify"] as const;
export type BriefKind = (typeof BRIEF_KINDS)[number];
export type ItemKind = "issue" | "change";

/** The work item behind a row. An issue's approval and not-started rows carry its fix plan as the entity. */
export function itemKind(item: Pick<AttentionItem, "entity">): ItemKind {
  return item.entity.entity_type === "change_request" ? "change" : "issue";
}

const TABLE: Record<string, BriefKind> = {
  "issue|approval_required|": "approve",
  "issue|verification_required|acceptance": "accept",
  "issue|verification_required|resolve": "resolve",
  "issue|review_required|rca_gate": "confirm",
  "issue|review_required|rca_missing": "rerun",
  "issue|review_required|rca_rejected": "rerun",
  "issue|review_required|rca_stopped": "rerun",          // its diagnosis ended without a result (N11): the same page, other words
  "issue|review_required|rca_confirmed": "generate",
  "issue|review_required|rca_ready": "generate",
  "issue|review_required|plan_rejected": "replan",
  "issue|execution_failed|run_failed": "failed",
  "issue|execution_failed|run_stopped": "failed",        // a person stopped the run (N9): the same page, other words
  "issue|execution_not_started|": "not_started",
  "change|review_required|change_draft": "start_review",
  "change|clarification_required|": "clarify",
  "change|approval_required|": "approve",
  "change|execution_not_started|": "not_started",
  "change|verification_required|acceptance": "accept",
};

/** null = a row this client does not know (a newer server): the page shows the generic brief, never a blank. */
export function briefKind(item: Pick<AttentionItem, "entity" | "reason" | "reason_detail">): BriefKind | null {
  return TABLE[`${itemKind(item)}|${item.reason}|${item.reason_detail ?? ""}`] ?? null;
}
