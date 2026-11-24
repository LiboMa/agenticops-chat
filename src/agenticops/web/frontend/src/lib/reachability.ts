import type { StatusTone } from "@/components/ui/StatusText";

/** A finding's / attack path's reachability as the security page shows it (MVP-2.8.0 S1 words, hardened in the
 *  S2 rework): the three states in words with their tone; an unknown string as written; any value that is not a
 *  string (some findings carry an evidence object) reads as undetermined — the engine's conservative bias for data
 *  it cannot read — and is never handed to React raw (it blanked the whole app). */
const TONE: Record<string, StatusTone> = { reachable: "danger", undetermined: "warn", not_reachable: "ok" };

export function reachView(value: unknown): { key: string | null; text: string | null; tone: StatusTone } | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") return { key: "security.reach.undetermined", text: null, tone: "warn" };
  return TONE[value] ? { key: `security.reach.${value}`, text: null, tone: TONE[value] } : { key: null, text: value, tone: "neutral" };
}
