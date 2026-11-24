/** The top bar's band «the last 24 hours» (N15): what happened, as the server's own record lists it
 *  (GET /api/ui/events) — an issue found, an agent's start and end, a person's decision, a change's course. */

export interface RecentEvent {
  id: number;
  at: string;
  kind: "signal" | "agent" | "decision" | "change";
  type: string;
  status: string;
  item: string | null;
  actor: string;
  detail: Record<string, string | number>;
}

export interface RecentEvents {
  events: RecentEvent[];
  total: number;
  /** more happened in the window than the server sends: the oldest were left out */
  cut: boolean;
  hours: number;
  from: string;
  to: string;
  generated_at: string;
}

export const BAND_HOURS = 24;
/** how many marks the band draws at most — the newest stay (a mark is 7 px wide: more would be one smear) */
export const MAX_TICKS = 240;

/** Where a moment `hoursAgo` sits on the band, in percent from the left. Recent hours get more room (a square
 *  root), the hour marks drawn with the same function keep it honest. */
export function pulseX(hoursAgo: number): number {
  const h = Math.min(Math.max(hoursAgo, 0), BAND_HOURS);
  return (1 - Math.sqrt(h / BAND_HOURS)) * 100;
}

export interface Tick { id: number; kind: RecentEvent["kind"]; left: number; event: RecentEvent }

/** The events as marks, oldest first: those of the last 24 hours that have a time, at most MAX_TICKS (the newest). */
export function bandTicks(events: RecentEvent[] | undefined, now: number): Tick[] {
  const out: Tick[] = [];
  for (const e of events ?? []) {
    const at = Date.parse(e.at);
    if (!Number.isFinite(at)) continue;
    const hoursAgo = (now - at) / 3_600_000;
    if (hoursAgo < 0 || hoursAgo > BAND_HOURS) continue;
    out.push({ id: e.id, kind: e.kind, left: pulseX(hoursAgo), event: e });
  }
  return out.slice(-MAX_TICKS);
}

/** The band in numbers — its accessible name says these (a mark's tooltip needs a pointer). */
export function bandTally(events: RecentEvent[] | undefined): Record<RecentEvent["kind"], number> {
  const n = { signal: 0, agent: 0, decision: 0, change: 0 };
  for (const e of events ?? []) if (e.kind in n) n[e.kind] += 1;
  return n;
}
