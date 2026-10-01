/**
 * Settings connector card logic (MVP-2.6.1 spec §3.E.5). Pure, so node can test it.
 */
import type { ConnectorStatus } from "@/api/types";

// connectors/ingest.py's counts, in the order a person reads a run
export const COUNT_KEYS = ["created", "updated", "absent", "returned", "signals", "signal_errors"] as const;

/** A run's non-zero counts in reading order; a key this build does not know yet goes last, not lost. */
export function countParts(counts: Record<string, number> | null | undefined): [string, number][] {
  const c = counts ?? {};
  const known = COUNT_KEYS.filter((k) => c[k]).map((k): [string, number] => [k, c[k]]);
  const other = Object.keys(c).filter((k) => c[k] && !(COUNT_KEYS as readonly string[]).includes(k)).sort();
  return [...known, ...other.map((k): [string, number] => [k, c[k]])];
}

/** Why "Run now" is unavailable, mirroring POST /api/connectors/{name}/run's 409s; null when it can run. */
export function runBlocker(c: Pick<ConnectorStatus, "enabled" | "running">): "disabled" | "running" | null {
  return !c.enabled ? "disabled" : c.running ? "running" : null;
}
