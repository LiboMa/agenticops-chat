import { describe, it, expect } from "vitest";
import { isComposingKey, shouldSend } from "@/lib/composerKeys";

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

import { fileDragAction } from "@/lib/composerKeys";
describe("fileDragAction — a dropped file never navigates away from the chat", () => {
  it("a file drag is always taken from the browser; it is attached only while the composer is enabled", () => {
    expect(fileDragAction(["Files"], false)).toEqual({ prevent: true, accept: true });
    expect(fileDragAction(["Files"], true)).toEqual({ prevent: true, accept: false });   // a reply is streaming
  });
  it("a text-selection drag is left alone", () => {
    expect(fileDragAction(["text/plain"], false)).toEqual({ prevent: false, accept: false });
    expect(fileDragAction(undefined, false)).toEqual({ prevent: false, accept: false });
  });
});

describe("isComposingKey — an input method is composing (MVP-2.8.0 S1, the search palette)", () => {
  it("is true while composing, or for Safari's keyCode 229", () => {
    expect(isComposingKey({ isComposing: true })).toBe(true);
    expect(isComposingKey({ isComposing: false, keyCode: 229 })).toBe(true);
  });
  it("is false for an ordinary key", () => {
    expect(isComposingKey({ isComposing: false, keyCode: 13 })).toBe(false);
    expect(isComposingKey({ isComposing: false })).toBe(false);
  });
});
