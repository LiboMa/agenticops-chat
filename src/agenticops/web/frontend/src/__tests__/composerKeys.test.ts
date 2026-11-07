import { describe, it, expect } from "vitest";
import { shouldSend } from "@/lib/composerKeys";

const k = (o = {}) => ({ key: "Enter", shiftKey: false, metaKey: false, ctrlKey: false, isComposing: false, ...o });

describe("shouldSend", () => {
  it("Enter sends on desktop; Shift+Enter is a newline", () => {
    expect(shouldSend(k(), false)).toBe(true);
    expect(shouldSend(k({ shiftKey: true }), false)).toBe(false);
  });
  it("never while an IME is composing (incl. Safari keyCode 229)", () => {
    expect(shouldSend(k({ isComposing: true }), false)).toBe(false);
    expect(shouldSend(k({ keyCode: 229 }), false)).toBe(false);
  });
  it("touch: Enter is a newline, Cmd/Ctrl+Enter still sends", () => {
    expect(shouldSend(k(), true)).toBe(false);
    expect(shouldSend(k({ metaKey: true }), true)).toBe(true);
    expect(shouldSend(k({ ctrlKey: true }), true)).toBe(true);
  });
  it("other keys never send", () => expect(shouldSend(k({ key: "a" }), false)).toBe(false));
});
