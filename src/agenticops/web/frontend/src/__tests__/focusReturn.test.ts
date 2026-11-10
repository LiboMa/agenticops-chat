import { describe, expect, it, vi } from "vitest";
import { closeFocusTarget, returnFocusTo } from "@/lib/focusReturn";

/** Radix returns focus only to a Dialog.Trigger; a dialog opened from any other button must hand it back itself
 *  (E2E finding, MVP-2.8.0 S2: after ESC on «验收本次执行» focus landed on <body>). */
describe("returnFocusTo", () => {
  it("focuses the opener that is still on the page and stops Radix's own (trigger-less) return", () => {
    const opener = { isConnected: true, focus: vi.fn() };
    const event = { preventDefault: vi.fn() };
    returnFocusTo(opener, event);
    expect(opener.focus).toHaveBeenCalledOnce();
    expect(event.preventDefault).toHaveBeenCalledOnce();
  });
  it("an opener that left the page (the item was handled) or none: Radix decides", () => {
    const gone = { isConnected: false, focus: vi.fn() };
    const event = { preventDefault: vi.fn() };
    returnFocusTo(gone, event);
    returnFocusTo(null, event);
    expect(gone.focus).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});

/** E2E finding (MVP-2.8.0 T11): after «删除用户» focus landed on <body> — Radix handed it back to the deleted row's
 *  button, still on the page when the dialog closed, and the list refetch then removed it. An action that removes
 *  its opener's row returns focus to the page's own button instead, decided before the dialog closes. */
describe("closeFocusTarget", () => {
  const opener = { id: "row" };
  const fallback = { id: "new-user" };
  it("the opener while it stays (cancel, ESC, a refused delete)", () => {
    expect(closeFocusTarget(opener, fallback, false)).toBe(opener);
  });
  it("the fallback once the action removed the opener's row", () => {
    expect(closeFocusTarget(opener, fallback, true)).toBe(fallback);
  });
  it("no fallback: the opener (Radix decides when it is gone)", () => {
    expect(closeFocusTarget(opener, null, true)).toBe(opener);
  });
});
