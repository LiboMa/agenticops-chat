import { describe, expect, it } from "vitest";
import { keyIntent, type KeyContext, type KeyEventLike } from "@/newui/lib/keys";

const ev = (key: string, over: Partial<KeyEventLike> = {}): KeyEventLike => ({
  key, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, isComposing: false, ...over,
});
const ctx = (over: Partial<KeyContext> = {}): KeyContext => ({ inField: false, onControl: false, modal: false, singleKeys: true, ...over });

describe("keyIntent — what a key press means in NewUI", () => {
  it("switches lens, theme, help and the command bar with single keys", () => {
    expect(keyIntent(ev("1"), ctx())).toEqual({ type: "lens", lens: "decide" });
    expect(keyIntent(ev("2"), ctx())).toEqual({ type: "lens", lens: "live" });
    expect(keyIntent(ev("3"), ctx())).toEqual({ type: "lens", lens: "world" });
    expect(keyIntent(ev("t"), ctx())).toEqual({ type: "theme" });
    expect(keyIntent(ev("T", { shiftKey: true }), ctx())).toEqual({ type: "theme" });
    expect(keyIntent(ev("?", { shiftKey: true }), ctx())).toEqual({ type: "help" });
    expect(keyIntent(ev("/"), ctx())).toEqual({ type: "command" });
  });

  it("hands every other key to the lens, lower-cased, with its repeat flag", () => {
    expect(keyIntent(ev("J"), ctx())).toEqual({ type: "lensKey", key: "j", repeat: false });
    expect(keyIntent(ev("a", { repeat: true }), ctx())).toEqual({ type: "lensKey", key: "a", repeat: true });
    expect(keyIntent(ev("ArrowDown"), ctx())).toEqual({ type: "lensKey", key: "arrowdown", repeat: false });
    expect(keyIntent(ev(" "), ctx())).toEqual({ type: "lensKey", key: " ", repeat: false });
    expect(keyIntent(ev("Enter"), ctx())).toEqual({ type: "lensKey", key: "enter", repeat: false });
  });

  it("does nothing while an input method is composing", () => {
    expect(keyIntent(ev("j", { isComposing: true }), ctx())).toBeNull();
    expect(keyIntent(ev("Enter", { keyCode: 229 }), ctx())).toBeNull();
    expect(keyIntent(ev("Process"), ctx())).toBeNull();
    expect(keyIntent(ev("Escape", { isComposing: true }), ctx())).toBeNull();
  });

  it("leaves a key with Ctrl / Cmd / Alt to the browser — except Cmd/Ctrl+K, the command bar", () => {
    expect(keyIntent(ev("r", { metaKey: true }), ctx())).toBeNull();
    expect(keyIntent(ev("a", { ctrlKey: true }), ctx())).toBeNull();
    expect(keyIntent(ev("d", { altKey: true }), ctx())).toBeNull();
    expect(keyIntent(ev("k", { metaKey: true }), ctx())).toEqual({ type: "command" });
    expect(keyIntent(ev("K", { ctrlKey: true }), ctx({ inField: true }))).toEqual({ type: "command" });
  });

  it("types into a field instead of acting; Escape still gets out", () => {
    expect(keyIntent(ev("a"), ctx({ inField: true }))).toBeNull();
    expect(keyIntent(ev("1"), ctx({ inField: true }))).toBeNull();
    expect(keyIntent(ev("/"), ctx({ inField: true }))).toBeNull();
    expect(keyIntent(ev("Escape"), ctx({ inField: true }))).toEqual({ type: "escape" });
  });

  it("leaves everything but Escape to an open dialog or menu", () => {
    expect(keyIntent(ev("a"), ctx({ modal: true }))).toBeNull();
    expect(keyIntent(ev("?", { shiftKey: true }), ctx({ modal: true }))).toBeNull();
    expect(keyIntent(ev("Enter"), ctx({ modal: true }))).toBeNull();
    expect(keyIntent(ev("Escape"), ctx({ modal: true }))).toEqual({ type: "escape" });
  });

  it("lets Space and Enter press the button that has the focus", () => {
    expect(keyIntent(ev(" "), ctx({ onControl: true }))).toBeNull();
    expect(keyIntent(ev("Enter"), ctx({ onControl: true }))).toBeNull();
    expect(keyIntent(ev("j"), ctx({ onControl: true }))).toEqual({ type: "lensKey", key: "j", repeat: false });
  });

  it("with single-key shortcuts switched off keeps only Escape and Cmd/Ctrl+K", () => {
    const off = ctx({ singleKeys: false });
    for (const k of ["a", "j", "1", "t", "/", "?", " ", "Enter", "ArrowDown"]) expect(keyIntent(ev(k), off), k).toBeNull();
    expect(keyIntent(ev("Escape"), off)).toEqual({ type: "escape" });
    expect(keyIntent(ev("k", { ctrlKey: true }), off)).toEqual({ type: "command" });
  });
});
