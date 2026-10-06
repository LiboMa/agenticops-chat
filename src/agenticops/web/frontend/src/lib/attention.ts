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

const REASONS = new Set(["approval_required", "clarification_required", "verification_required", "execution_failed",
  "review_required", "execution_not_started"]);
const DETAILS = new Set(["run_failed", "plan_rejected", "rca_missing", "rca_gate", "rca_rejected", "rca_confirmed",
  "acceptance", "resolve", "change_draft"]);

export const countLabel = (n: number): string => (n > 99 ? "99+" : String(n));

/** The row's sentence: its detail when this client knows it, else its reason, else a neutral line (a newer server). */
export function reasonKey(i: Pick<AttentionItem, "reason" | "reason_detail">): string {
  if (i.reason_detail && DETAILS.has(i.reason_detail)) return `attention.detail.${i.reason_detail}`;
  return REASONS.has(i.reason) ? `attention.reason.${i.reason}` : "attention.reason.unknown";
}

/** A row's route, only if it stays inside the app (never the login page, never a parent-path trick). */
export function safeRoute(route: unknown): string | null {
  if (typeof route !== "string" || !/^\/app\/[A-Za-z0-9/_#-]*$/.test(route)) return null;
  if (route.includes("..") || route.startsWith("/app/login")) return null;
  return route;
}
