/** «Approve» changes infrastructure, so the key (or the button) must be HELD — and the hold approves only what was
 *  on the page when it began. The queue refreshes every 30 s and may put another item under the same key; a plan can
 *  be edited while it is being read. So the hold captures its target and gives up the moment the page shows anything
 *  else. Pure: the component feeds it events and does what it says. */
export const HOLD_MS = 900;

export interface HoldTarget { itemId: string; planId: number; hash: string }

export type HoldState = { phase: "idle" } | { phase: "holding"; target: HoldTarget; since: number };

export type HoldEvent =
  | { type: "down"; target: HoldTarget | null; at: number }          // the key or the pointer went down
  | { type: "up"; at: number }                                       // … and came up
  | { type: "tick"; at: number; shown: HoldTarget | null }           // time passed; `shown` = what the page holds now
  | { type: "cancel" };                                              // focus left, the tab was hidden, another key

export interface HoldResult {
  state: HoldState;
  /** approve exactly this — never read the page again to find out what */
  fire: HoldTarget | null;
  /** it was let go too early: say «keep holding» */
  hint: boolean;
}

export function sameTarget(a: HoldTarget | null, b: HoldTarget | null): boolean {
  return !!a && !!b && a.itemId === b.itemId && a.planId === b.planId && a.hash === b.hash;
}

const IDLE: HoldState = { phase: "idle" };

export function holdStep(state: HoldState, event: HoldEvent, holdMs: number = HOLD_MS): HoldResult {
  if (state.phase === "idle") {
    return event.type === "down" && event.target
      ? { state: { phase: "holding", target: event.target, since: event.at }, fire: null, hint: false }
      : { state: IDLE, fire: null, hint: false };
  }
  switch (event.type) {
    case "down":
      return { state, fire: null, hint: false };
    case "up":
      return { state: IDLE, fire: null, hint: true };
    case "cancel":
      return { state: IDLE, fire: null, hint: false };
    case "tick":
      if (!sameTarget(state.target, event.shown)) return { state: IDLE, fire: null, hint: false };
      return event.at - state.since >= holdMs ? { state: IDLE, fire: state.target, hint: false } : { state, fire: null, hint: false };
  }
}
