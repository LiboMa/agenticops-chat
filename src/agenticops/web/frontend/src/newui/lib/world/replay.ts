/** «Back in time» on the map (N15): a moment of the last 24 hours instead of now. What can be shown for it is
 *  which resources had an open issue then and which a scan had already stopped seeing (GET /api/galaxy/health?at=);
 *  the relations, each issue's severity and its anchor are today's — the page says so. `null` is «now». */

export const REPLAY_MS = 24 * 3_600_000;
/** the slider's step */
export const STEP_MS = 5 * 60_000;
const STEPS = REPLAY_MS / STEP_MS;

/** The slider's value (0 = 24 hours ago … STEPS = now) as a moment; the right end is «now» (null). */
export function atOf(value: number, now: number): number | null {
  const v = Math.round(value);
  return v >= STEPS ? null : now - REPLAY_MS + Math.max(v, 0) * STEP_MS;
}

/** A moment as the slider's value: the step nearest to it, kept inside the day. Nearest, not «at or before»: the
 *  clock runs while a moment is shown, and a moment picked on a step must not slip to the step before a second
 *  later. A past moment is never the right end (that is «now»). */
export function valueOf(at: number | null, now: number): number {
  if (at === null || at >= now) return STEPS;
  return Math.min(Math.max(Math.round((at - (now - REPLAY_MS)) / STEP_MS), 0), STEPS - 1);
}

/** The times at which something happened, oldest first: the events' own times inside the day, a minute at most
 *  once (several events of one minute are one moment to go to). */
export function moments(events: { at: string }[] | undefined, now: number): number[] {
  const out: number[] = [];
  let lastMinute = -1;
  for (const e of [...(events ?? [])].map((x) => Date.parse(x.at)).filter((t) => Number.isFinite(t) && t <= now && t >= now - REPLAY_MS).sort((a, b) => a - b)) {
    const minute = Math.floor(e / 60_000);
    if (minute !== lastMinute) { out.push(e); lastMinute = minute; }
  }
  return out;
}

/** `[` (dir −1) and `]` (dir +1): the moment of the event before / after `at`. Before the oldest there is nothing
 *  to go to (it stays); after the newest comes now (null). */
export function jump(ms: number[], at: number | null, dir: -1 | 1): number | null {
  if (dir < 0) {
    const older = ms.filter((m) => at === null || m < at);
    return older.length ? older[older.length - 1] : at;
  }
  if (at === null) return null;
  return ms.find((m) => m > at) ?? null;
}

/** `P`: the moments to show, in order, ending at now. With more than `max` moments a spread sample of them — the
 *  first and the last always in it — so a busy day still plays in a bounded time. Nothing when nothing happened. */
export function playPlan(ms: number[], max: number): (number | null)[] {
  if (!ms.length) return [];
  if (ms.length <= max) return [...ms, null];
  const out: (number | null)[] = [];
  for (let i = 0; i < max; i++) out.push(ms[Math.round((i * (ms.length - 1)) / (max - 1))]);
  return [...out, null];
}
