import { describe, expect, it } from "vitest";
import { Pending, UNDO_MS, deferDecision, type Clock } from "@/newui/lib/pending";

/** A clock the test moves by hand: timers fire when `tick` passes their time, in order. */
function fakeClock() {
  let t = 0, seq = 0;
  const timers = new Map<number, { at: number; fn: () => void }>();
  const clock: Clock = {
    now: () => t,
    set: (fn, ms) => { timers.set(++seq, { at: t + ms, fn }); return seq; },
    clear: (h) => { timers.delete(h as number); },
  };
  const tick = (ms: number) => {
    const end = t + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, x]) => x.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]); t = due[1].at; due[1].fn();
    }
    t = end;
  };
  return { clock, tick };
}

const decision = (label: string, log: string[]) => ({ label, send: () => { log.push(`send ${label}`); }, undo: () => { log.push(`undo ${label}`); } });

describe("Pending — a decision shows at once and is sent a little later", () => {
  it("waits five seconds, as the design says", () => {
    expect(UNDO_MS).toBe(5000);
  });

  it("sends the decision when its time is up — not before", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add(decision("approve I12", log));
    expect(p.waiting).toEqual({ label: "approve I12", due: 5000 });
    tick(4999);
    expect(log).toEqual([]);
    tick(1);
    expect(log).toEqual(["send approve I12"]);
    expect(p.waiting).toBeNull();
  });

  it("taken back in time, it is never sent", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add(decision("approve I12", log));
    tick(3000);
    expect(p.undo()).toBe(true);
    expect(log).toEqual(["undo approve I12"]);
    tick(10_000);
    expect(log).toEqual(["undo approve I12"]);               // its timer is gone with it
    expect(p.undo()).toBe(false);                             // nothing is waiting any more
  });

  it("cannot be taken back once it was sent", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add(decision("dismiss I7", log));
    tick(5000);
    expect(p.undo()).toBe(false);
    expect(log).toEqual(["send dismiss I7"]);
  });

  it("a new decision sends the one before it at once — only the last one can be undone", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add(decision("approve I12", log));
    tick(1000);
    p.add(decision("dismiss I7", log));
    expect(log).toEqual(["send approve I12"]);
    expect(p.waiting).toEqual({ label: "dismiss I7", due: 6000 });
    expect(p.undo()).toBe(true);
    expect(log).toEqual(["send approve I12", "undo dismiss I7"]);
    tick(10_000);
    expect(log).toEqual(["send approve I12", "undo dismiss I7"]);      // the first one is not sent a second time
  });

  it("is sent now when the page goes away — the person had decided", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add(decision("approve I12", log));
    tick(1200);
    p.flush();
    expect(log).toEqual(["send approve I12"]);
    tick(10_000);
    expect(log).toEqual(["send approve I12"]);
    p.flush();                                                // nothing waits: nothing happens
    expect(log).toEqual(["send approve I12"]);
  });

  it("tells whoever draws the toast every time what is waiting changes", () => {
    const { clock, tick } = fakeClock(), seen: (string | null)[] = [];
    const p = new Pending(clock);
    const stop = p.subscribe(() => seen.push(p.waiting?.label ?? null));
    p.add(decision("a", []));
    p.add(decision("b", []));
    p.undo();
    p.add(decision("c", []));
    tick(5000);
    expect(seen).toEqual(["a", null, "b", null, "c", null]);
    stop();
    p.add(decision("d", []));
    expect(seen.length).toBe(6);
  });

  it("a decision whose send throws does not keep the next one from waiting", () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    p.add({ label: "bad", send: () => { throw new Error("boom"); }, undo: () => {} });
    p.add(decision("good", log));
    expect(p.waiting?.label).toBe("good");
    tick(5000);
    expect(log).toEqual(["send good"]);
  });
});

describe("deferDecision — a queue decision: shown now, sent later, put back when it fails or is taken back", () => {
  const setup = () => {
    const { clock, tick } = fakeClock(), log: string[] = [];
    const p = new Pending(clock);
    let settle: { ok: (v: string) => void; fail: (e: unknown) => void } | null = null;
    const d = {
      label: "approve I12",
      hide: () => { log.push("hide"); return (goBack: boolean) => { log.push(goBack ? "restore and go back" : "restore"); }; },
      request: () => { log.push("request"); return new Promise<string>((ok, fail) => { settle = { ok, fail }; }); },
      onDone: (r: string) => { log.push(`done ${r}`); },
      onFailed: (e: unknown) => { log.push(`failed ${String(e)}`); },
    };
    return { p, tick, log, d, settle: () => settle! };
  };
  const flushed = () => new Promise((r) => setTimeout(r, 0));

  it("hides the item at once and sends nothing until the window is over", async () => {
    const { p, tick, log, d, settle } = setup();
    deferDecision(p, d);
    expect(log).toEqual(["hide"]);
    tick(4999);
    expect(log).toEqual(["hide"]);
    tick(1);
    expect(log).toEqual(["hide", "request"]);
    settle().ok("queued");
    await flushed();
    expect(log).toEqual(["hide", "request", "done queued"]);
  });

  it("taken back: the item returns and the request is never made", () => {
    const { p, tick, log, d } = setup();
    deferDecision(p, d);
    tick(2000);
    expect(p.undo()).toBe(true);
    tick(10_000);
    expect(log).toEqual(["hide", "restore and go back"]);            // the person took it back: the page returns to it
  });

  it("refused by the server after the window: the item returns and the failure is said", async () => {
    const { p, tick, log, d, settle } = setup();
    deferDecision(p, d);
    tick(5000);
    settle().fail("409 the plan changed");
    await flushed();
    expect(log).toEqual(["hide", "request", "restore", "failed 409 the plan changed"]);
  });

  it("a request that throws before it is even sent is a failure too", async () => {
    const { p, tick, log, d } = setup();
    deferDecision(p, { ...d, request: () => { log.push("request"); throw new Error("offline"); } });
    tick(5000);
    await flushed();
    expect(log).toEqual(["hide", "request", "restore", "failed Error: offline"]);
  });
});
