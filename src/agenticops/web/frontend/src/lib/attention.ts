import type { UiAction } from "@/api/types";

export const ATTENTION_QUERY_KEY = ["ui-attention"] as const;
export type AttentionReason = "approval_required" | "clarification_required" | "verification_required"
  | "execution_failed" | "review_required" | "execution_not_started";
export interface AttentionItem {
  id: string; ref: string; reason: AttentionReason | string; reason_detail: string | null; title: string;
  entity: { entity_type: string; entity_id: number; content_version: number | null };
  account_id: number | null; occurred_at: string; route: string; available_actions: UiAction[];
}
export interface AttentionPage { items: AttentionItem[]; total: number; next_cursor: string | null; generated_at: string }

/** The hub's tab counts: approval and "not started" rows of fix plans → Fix plans; change rows → Changes. */
export function tabCounts(items: AttentionItem[]): { fix: number; changes: number } {
  return {
    fix: items.filter((i) => i.entity.entity_type === "fix_plan").length,
    changes: items.filter((i) => i.entity.entity_type === "change_request").length,
  };
}
