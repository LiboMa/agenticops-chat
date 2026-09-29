/**
 * Galaxy's four-value node health (MVP-2.6.1).
 *
 * Mirrors `graph/query_service.HEALTH_RANK`. The server reports the worst open issue of a
 * resource; a resource with no open issue is `unknown` — no alert is not the same as healthy
 * (spec §3.A.6). Anything else the client sees (missing, or a pre-2.6.1 "healthy") is `unknown`.
 */
import type { GalaxyHealth } from "@/api/types";

export const HEALTH_VALUES: readonly GalaxyHealth[] = ["unknown", "notice", "warning", "critical"];

export function normalizeHealth(h?: string | null): GalaxyHealth {
  return HEALTH_VALUES.find((v) => v === h) ?? "unknown";
}

/** Warning and critical stars pulse; notice is coloured but still. */
export function isHot(h: GalaxyHealth): boolean {
  return h === "warning" || h === "critical";
}

/** Legend tallies over resource nodes; account and group nodes carry no health. */
export function healthCounts(nodes: { kind: string; health?: string }[]): Record<GalaxyHealth, number> {
  const counts: Record<GalaxyHealth, number> = { unknown: 0, notice: 0, warning: 0, critical: 0 };
  for (const n of nodes) if (n.kind === "resource") counts[normalizeHealth(n.health)]++;
  return counts;
}
