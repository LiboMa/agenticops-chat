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

import { keepsImeEnter } from "@/lib/composerKeys";
describe("keepsImeEnter — a field inside a <form>: the Enter that picks a candidate must not submit it", () => {
  // Round-2 review (B, S1). The reason box and the «say a word» field submit through the browser's own form
  // submission. Chrome keeps the candidate-picking Enter to the input method; Safari ends the composition first and
  // then delivers that Enter (keyCode 229, isComposing false) — and submits the form with a half-typed sentence.
  const ev = (over: Partial<{ key: string; isComposing: boolean; keyCode: number }> = {}) => {
    let prevented = false;
    return { e: { key: over.key ?? "Enter", preventDefault: () => { prevented = true; },
                  nativeEvent: { isComposing: over.isComposing ?? false, keyCode: over.keyCode ?? 13 } },
             prevented: () => prevented };
  };
  it("stops Safari's Enter after a composition, and an Enter during one", () => {
    const safari = ev({ keyCode: 229 });
    expect([keepsImeEnter(safari.e), safari.prevented()]).toEqual([true, true]);
    const composing = ev({ isComposing: true });
    expect([keepsImeEnter(composing.e), composing.prevented()]).toEqual([true, true]);
  });
  it("leaves an ordinary Enter and every other key alone", () => {
    const enter = ev();
    expect([keepsImeEnter(enter.e), enter.prevented()]).toEqual([false, false]);
    const letter = ev({ key: "a", keyCode: 229 });                     // typing a candidate's letters: the input method's own
    expect([keepsImeEnter(letter.e), letter.prevented()]).toEqual([false, false]);
  });
});
