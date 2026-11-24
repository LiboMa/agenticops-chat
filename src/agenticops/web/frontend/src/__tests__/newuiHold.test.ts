import { describe, expect, it } from "vitest";
import { HOLD_MS, holdStep, sameTarget, type HoldState, type HoldTarget } from "@/newui/lib/hold";

const A: HoldTarget = { itemId: "I12", planId: 10, hash: "abc" };
const B: HoldTarget = { itemId: "I10", planId: 11, hash: "def" };
const idle: HoldState = { phase: "idle" };
const down = (target: HoldTarget | null, at = 0) => holdStep(idle, { type: "down", target, at });

describe("holdStep — «approve» must be held, and only approves what was on the page when the hold began", () => {
  it("starts holding on the target that is shown", () => {
    expect(down(A, 100)).toEqual({ state: { phase: "holding", target: A, since: 100 }, fire: null, hint: false });
  });

  it("does not start without a target (the plan is still loading, or may not be approved)", () => {
    expect(down(null)).toEqual({ state: idle, fire: null, hint: false });
  });

  it("fires the target it started with once the time is up", () => {
    const holding = down(A).state;
    expect(holdStep(holding, { type: "tick", at: HOLD_MS - 1, shown: A }).fire).toBeNull();
    expect(holdStep(holding, { type: "tick", at: HOLD_MS, shown: A })).toEqual({ state: idle, fire: A, hint: false });
  });

  it("lets go early: nothing happens, and the button says to keep holding", () => {
    expect(holdStep(down(A).state, { type: "up", at: 300 })).toEqual({ state: idle, fire: null, hint: true });
  });

  it("never fires when another item took the page during the hold (the queue reorders every 30 s)", () => {
    const holding = down(A).state;
    expect(holdStep(holding, { type: "tick", at: HOLD_MS + 50, shown: B })).toEqual({ state: idle, fire: null, hint: false });
    expect(holdStep(holding, { type: "tick", at: HOLD_MS + 50, shown: null })).toEqual({ state: idle, fire: null, hint: false });
  });

  it("never fires when the same plan changed under the hold (a new content hash)", () => {
    const holding = down(A).state;
    expect(holdStep(holding, { type: "tick", at: HOLD_MS, shown: { ...A, hash: "changed" } }).fire).toBeNull();
  });

  it("is cancelled by anything else: the window losing focus, the tab going to the background, another key", () => {
    expect(holdStep(down(A).state, { type: "cancel" })).toEqual({ state: idle, fire: null, hint: false });
  });

  it("ignores a second press while already holding, and a release or a tick when idle", () => {
    const holding = down(A, 0).state;
    expect(holdStep(holding, { type: "down", target: B, at: 400 }).state).toEqual(holding);
    expect(holdStep(idle, { type: "up", at: 10 })).toEqual({ state: idle, fire: null, hint: false });
    expect(holdStep(idle, { type: "tick", at: 5000, shown: A })).toEqual({ state: idle, fire: null, hint: false });
  });

  it("compares targets by item, plan and hash", () => {
    expect(sameTarget(A, { ...A })).toBe(true);
    expect(sameTarget(A, { ...A, planId: 99 })).toBe(false);
    expect(sameTarget(A, null)).toBe(false);
  });
});
