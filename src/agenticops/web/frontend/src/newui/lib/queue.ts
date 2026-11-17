import type { AttentionItem } from "@/lib/attention";
import { parseApiDate } from "@/lib/formatDate";
import { DECISION_GROUPS, groupOf, type DecisionGroup } from "@/lib/inbox";

/** «待决»: the queue of things that wait on you. The server sorts it (sort=severity: the most severe first, then the
 *  longest wait) and counts it; this file only reads what came back. */

/** The filter pills, in the design's order. The groups are the server's decision groups (lib/inbox, shared fixture). */
export const FILTERS = ["all", "approval", "acceptance", "confirm", "failed"] as const;
export type QueueFilter = (typeof FILTERS)[number];

const REASONS = ["approval_required", "clarification_required", "execution_failed", "execution_not_started",
  "review_required", "verification_required"] as const;

export function parseFilter(raw: string | null | undefined): QueueFilter {
  return (FILTERS as readonly string[]).includes(raw ?? "") ? (raw as QueueFilter) : "all";
}

/** The `reason` parameter for a filter: the reasons of that group, sorted (a stable cache key); null = no filter. */
export function reasonsParam(filter: QueueFilter): string | null {
  if (filter === "all") return null;
  return REASONS.filter((r) => groupOf(r) === filter).join(",");
}

export type GroupCounts = Record<QueueFilter, number>;

/** The server's per-reason counts as the pills' numbers. null when the counts did not arrive: the page shows «—»,
 *  never a 0 it did not count. A reason this client does not know still counts toward the total. */
export function groupCounts(counts: Record<string, number> | null | undefined): GroupCounts | null {
  if (!counts) return null;
  const out: GroupCounts = { all: 0, approval: 0, acceptance: 0, confirm: 0, failed: 0 };
  for (const [reason, n] of Object.entries(counts)) {
    out.all += n;
    const g: DecisionGroup | null = groupOf(reason);
    if (g && (DECISION_GROUPS as readonly string[]).includes(g)) out[g] += n;
  }
  return out;
}

/** The pages as one list, in the server's order. Pages are cut by offset, so when an item leaves the queue between two
 *  requests a later page can repeat one: the first sighting stays. */
export function flattenPages(pages: { items: AttentionItem[] }[] | undefined): AttentionItem[] {
  const seen = new Set<string>(), out: AttentionItem[] = [];
  for (const p of pages ?? []) for (const i of p.items) if (!seen.has(i.id)) { seen.add(i.id); out.push(i); }
  return out;
}

/** The item on the page: the selected one wherever the list now has it; when it has left, the item now at the place
 *  it had (the last one when the list got shorter). */
export function currentItem<T extends { id: string }>(items: T[], curId: string | null, curIdx: number): { item: T; index: number } | null {
  if (!items.length) return null;
  let index = curId ? items.findIndex((i) => i.id === curId) : -1;
  if (index < 0) index = Math.min(Math.max(curIdx, 0), items.length - 1);
  return { item: items[index], index };
}

/** J / K: the next or previous place, round the ends. */
export function step(length: number, index: number, delta: number): number {
  return length ? (index + delta + length) % length : 0;
}

export type EmptyKind = "readOnly" | "filtered" | "clear";

/** Why nothing is listed. A read-only account is never handed a decision — that is not «all done». */
export function emptyKind({ filter, counts, readOnly }: { filter: QueueFilter; counts: GroupCounts | null; readOnly: boolean }): EmptyKind {
  if (readOnly) return "readOnly";
  return filter !== "all" && !!counts && counts.all > 0 ? "filtered" : "clear";
}

export type Tone = "crit" | "warn" | "info" | "";
const SEVERITY_TONE: Record<string, Tone> = { critical: "crit", high: "warn", medium: "warn", low: "info" };
const RISK_TONE: Record<string, Tone> = { L3: "crit", L2: "warn", L1: "info", L0: "info" };

/** The colour of a row's edge: an issue's severity, a change's risk level; plain when neither is known. */
export function toneOf(item: Pick<AttentionItem, "severity" | "risk_level">): Tone {
  return SEVERITY_TONE[item.severity ?? ""] ?? RISK_TONE[item.risk_level ?? ""] ?? "";
}

export interface Waited { unit: "now" | "min" | "hour" | "day"; n: number }

/** How long something has waited, in whole units rounded down — the same numbers as the classic page (lib/inbox). */
export function waitedParts(sinceIso: string | null | undefined, now: number): Waited | null {
  const since = parseApiDate(sinceIso ?? null);
  if (!since || Number.isNaN(since.getTime())) return null;
  const minutes = Math.floor((now - since.getTime()) / 60_000);
  if (minutes < 1) return { unit: "now", n: 0 };
  if (minutes < 60) return { unit: "min", n: minutes };
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? { unit: "hour", n: hours } : { unit: "day", n: Math.floor(hours / 24) };
}

/** An address that names an item: on the list ("found"), maybe on a page not fetched yet ("loading" — fetch on), or
 *  not waiting on you ("gone": handled, or never yours). */
export function deepLinkState({ item, items, ready, hasMore }:
    { item: string | null; items: { id: string }[]; ready: boolean; hasMore: boolean }): "none" | "found" | "loading" | "gone" {
  if (!item) return "none";
  if (items.some((i) => i.id === item)) return "found";
  return !ready || hasMore ? "loading" : "gone";
}
