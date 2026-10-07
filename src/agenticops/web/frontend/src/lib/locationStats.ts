/**
 * AgentMetrics RCA-location card logic (MVP-2.6.1 spec §3.E.5): the order the breakdowns read in and the rate
 * format. Pure, so node can test it.
 */
import type { AnchorStatus, LocationStatus } from "@/api/types";

export const LOCATION_STATUSES: readonly LocationStatus[] = ["valid", "partial", "invalid", "absent"];
export const ANCHOR_STATUSES: readonly AnchorStatus[] = ["anchored", "account_level", "ambiguous", "unanchored"];

/** 0.8333 → "83%"; null (nothing to divide by) → "—", never a misleading 0%. */
export function ratePct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
