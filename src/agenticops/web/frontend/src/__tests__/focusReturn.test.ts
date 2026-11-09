import { describe, expect, it, vi } from "vitest";
import { returnFocusTo } from "@/lib/focusReturn";

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
