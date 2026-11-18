/** A decision that shows at once and is sent a little later: until then it can be taken back (MVP-2.9.0 N13).
 *
 *  The design's rule (`store.act` in the prototype): what the person decided is shown immediately; it takes effect
 *  after UNDO_MS; until then «undo» takes it back and nothing has happened anywhere — the request was never sent.
 *  One decision waits at a time: a new one sends the one before it at once, so only the last decision can be
 *  undone. When the page goes away the waiting decision is sent now — the person had decided.
 *
 *  No React and no timers of its own: the clock is handed in, so the rules are tested with a clock the test moves. */

export const UNDO_MS = 5000;

export interface Deferred {
  /** what the toast says while it waits */
  label: string;
  /** do it now (the request leaves) */
  send: () => void;
  /** it was taken back: put the page back as it was */
  undo: () => void;
}

export interface Clock {
  now: () => number;
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}

export const browserClock: Clock = {
  now: () => Date.now(),
  set: (fn, ms) => window.setTimeout(fn, ms),
  clear: (handle) => window.clearTimeout(handle as number),
};

export class Pending {
  private cur: { d: Deferred; due: number; timer: unknown } | null = null;
  private listeners = new Set<() => void>();

  constructor(private clock: Clock = browserClock, private ms: number = UNDO_MS) {}

  /** what is waiting to be sent, and when it will be (epoch ms of the clock) */
  get waiting(): { label: string; due: number } | null {
    return this.cur ? { label: this.cur.d.label, due: this.cur.due } : null;
  }

  /** A new decision: the one before it is sent now, this one waits. */
  add(d: Deferred): void {
    this.flush();
    this.cur = { d, due: this.clock.now() + this.ms, timer: this.clock.set(() => this.flush(), this.ms) };
    this.tell();
  }

  /** Take the waiting decision back. false = nothing was waiting (it was sent, or there never was one). */
  undo(): boolean {
    const cur = this.take();
    if (!cur) return false;
    cur.d.undo();
    return true;
  }

  /** Send the waiting decision now: its time is up, a new decision came, or the page is going away. */
  flush(): void {
    const cur = this.take();
    if (!cur) return;
    try { cur.d.send(); } catch { /* the sender reports its own failure; the next decision must still be able to wait */ }
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private take() {
    const cur = this.cur;
    if (!cur) return null;
    this.clock.clear(cur.timer);
    this.cur = null;
    this.tell();
    return cur;
  }

  private tell(): void {
    for (const l of [...this.listeners]) l();
  }
}

/** One decision on a queue item, deferred: the item leaves the list NOW (`hide` returns «put it back»), the request
 *  is made when the window is over, and the item comes back when the decision is taken back or the server refuses
 *  it — a refusal after the window is said (`onFailed`), never silent. */
export function deferDecision<T>(p: Pick<Pending, "add">, d: {
  label: string;
  /** hide the item now → «put it back»; `goBack` = also bring the page back to it (the person took the decision
   *  back themselves — a refusal that arrives later must not pull them away from what they are doing now) */
  hide: () => (goBack: boolean) => void;
  request: () => Promise<T>;
  onDone: (result: T) => void;
  onFailed: (e: unknown) => void;
}): void {
  const restore = d.hide();
  const refused = (e: unknown) => { restore(false); d.onFailed(e); };
  p.add({
    label: d.label,
    send: () => {
      let sent: Promise<T>;
      try { sent = d.request(); } catch (e) { refused(e); return; }
      sent.then(d.onDone, refused);
    },
    undo: () => restore(true),
  });
}
