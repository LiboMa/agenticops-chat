import { afterEach, describe, expect, it } from "vitest";
import { closesOnEscape, openOverlay } from "@/lib/escapeStack";

const esc = { key: "Escape", defaultPrevented: false };
const releases: Array<() => void> = [];
const open = (close: () => void) => { const release = openOverlay(close); releases.push(release); return release; };
afterEach(() => { while (releases.length) releases.pop()!(); });

describe("which overlay an Escape key press closes (MVP-2.9.0 N25 — the house rule: every dialog closes on Escape)", () => {
  it("the overlay that is open", () => {
    const a = () => {};
    expect(closesOnEscape(a, esc)).toBe(false);          // not open: nothing to close
    open(a);
    expect(closesOnEscape(a, esc)).toBe(true);
  });
  it("of several, only the one opened last — and the one under it once that has closed", () => {
    const a = () => {}, b = () => {};
    open(a);
    const closeB = open(b);
    expect(closesOnEscape(b, esc)).toBe(true);
    expect(closesOnEscape(a, esc)).toBe(false);
    closeB();
    expect(closesOnEscape(a, esc)).toBe(true);
    closeB();                                              // closing twice takes nothing else away
    expect(closesOnEscape(a, esc)).toBe(true);
  });
  it("an overlay that closed out of turn is no longer in the way", () => {
    const a = () => {}, b = () => {}, c = () => {};
    open(a);
    const closeB = open(b);
    open(c);
    closeB();
    expect(closesOnEscape(c, esc)).toBe(true);
    expect(closesOnEscape(a, esc)).toBe(false);
  });
  it("only the Escape key", () => {
    const a = () => {};
    open(a);
    expect(closesOnEscape(a, { key: "Enter", defaultPrevented: false })).toBe(false);
    expect(closesOnEscape(a, { key: "Esc", defaultPrevented: false })).toBe(false);
  });
  it("not when something above already took the key (a Radix dialog marks it handled)", () => {
    const a = () => {};
    open(a);
    expect(closesOnEscape(a, { key: "Escape", defaultPrevented: true })).toBe(false);
  });
  it("not while an input method composes — there Escape cancels the composition", () => {
    const a = () => {};
    open(a);
    expect(closesOnEscape(a, { key: "Escape", defaultPrevented: false, isComposing: true })).toBe(false);
    expect(closesOnEscape(a, { key: "Escape", defaultPrevented: false, keyCode: 229 })).toBe(false);
  });
});
