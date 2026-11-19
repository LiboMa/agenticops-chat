import { describe, expect, it } from "vitest";
import {
  SWAP_GUARD_MS, TYPING_GRACE_MS, endsTyping, escapeStep, keyIntent, stillTyping, swapGuard, toastMs, type KeyContext, type KeyEventLike,
  focusContext,
} from "@/newui/lib/keys";

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

describe("escapeStep — what Escape does, one layer at a time", () => {
  const nothing = { help: false, menu: false, inField: false };
  it("closes the keyboard list or the account menu first", () => {
    expect(escapeStep({ ...nothing, help: true, inField: true })).toBe("help");
    expect(escapeStep({ ...nothing, menu: true })).toBe("menu");
  });
  it("while typing, only leaves the field — it never closes a page or an open resource under the person's hands", () => {
    expect(escapeStep({ ...nothing, inField: true })).toBe("blur");
  });
  it("otherwise belongs to the lens", () => {
    expect(escapeStep(nothing)).toBe("lens");
  });
});

describe("typing does not turn into decisions when the field goes away under the hands", () => {
  // a reason box can disappear mid-sentence: a colleague decided the item, the 30-second refresh replaced the page
  it("for a moment after a key went into a field, single keys are still typing", () => {
    expect(stillTyping(1000, 1000 + TYPING_GRACE_MS - 1)).toBe(true);
    expect(stillTyping(1000, 1000 + TYPING_GRACE_MS)).toBe(false);
    expect(stillTyping(null, 5000)).toBe(false);
  });

  it("a key that is still typing means nothing to a lens — but Escape and Cmd/Ctrl+K keep working", () => {
    const typing = ctx({ typing: true });
    expect(keyIntent(ev("d"), typing)).toBeNull();
    expect(keyIntent(ev("Enter"), typing)).toBeNull();
    expect(keyIntent(ev("1"), typing)).toBeNull();
    expect(keyIntent(ev("Escape"), typing)).toEqual({ type: "escape" });
    expect(keyIntent(ev("k", { metaKey: true }), typing)).toEqual({ type: "command" });
  });

  it("the keys that send or leave a field end the typing: J right after a sent reason must work", () => {
    expect(["Enter", "Escape", "Tab"].map(endsTyping)).toEqual([true, true, true]);
    expect(["a", " ", "Backspace", "，"].map(endsTyping)).toEqual([false, false, false, false]);
  });
});

describe("swapGuard — a brief the person did not open does not take their keys at once", () => {
  it("guards when the page changed by itself: the item was decided elsewhere, changed situation, or a decision moved on", () => {
    expect(swapGuard("I12:approve", "I13:approve", false, 5000)).toBe(5000 + SWAP_GUARD_MS);
    expect(swapGuard("I12:confirm", "I12:generate", false, 5000)).toBe(5000 + SWAP_GUARD_MS);
    expect(swapGuard("I12:approve", "gone:I12", false, 5000)).toBe(5000 + SWAP_GUARD_MS);
  });

  it("does not guard the person's own J / K / click, the first page, or a page that did not change", () => {
    expect(swapGuard("I12:approve", "I13:approve", true, 5000)).toBeNull();
    expect(swapGuard(null, "I12:approve", false, 5000)).toBeNull();
    expect(swapGuard("I12:approve", "I12:approve", false, 5000)).toBeNull();
  });
});

describe("toastMs — a toast stays long enough to be read", () => {
  it("a short line as before, a long refusal longer, never forever", () => {
    expect(toastMs("已批准 I#12")).toBe(2600);
    expect(toastMs("x".repeat(60))).toBe(4200);
    expect(toastMs("x".repeat(400))).toBe(9000);
  });
});


describe("focusContext — where the focus is decides whether a letter is typing (N15)", () => {
  const el = (tagName: string, attrs: Record<string, string> = {}) =>
    ({ tagName, isContentEditable: false, getAttribute: (k: string) => attrs[k] ?? null, ...attrs }) as unknown as Element;

  it("a text box, a text area and a select take the keys", () => {
    for (const e of [el("INPUT"), el("INPUT", { type: "text" }), el("INPUT", { type: "search" }), el("TEXTAREA"), el("SELECT")]) {
      expect(focusContext(e).inField).toBe(true);
    }
  });

  it("a slider does not: nothing can be typed into it, so the page's keys go on working after it was dragged", () => {
    // found in the browser: after moving the map's time slider, «0» (back to now) did nothing until the focus left it
    expect(focusContext(el("INPUT", { type: "range" }))).toEqual({ inField: false, onControl: false });
  });

  it("a button and a link keep Space and Enter", () => {
    expect(focusContext(el("BUTTON")).onControl).toBe(true);
    expect(focusContext(el("A")).onControl).toBe(true);
    expect(focusContext(null)).toEqual({ inField: false, onControl: false });
  });
});

describe("on a hosted classic page the shell's keys stand back", () => {
  // a classic page has its own dialogs, menus and rows; the shell cannot see them (its `modal` is its own help / menu)
  const hosted = ctx({ hosted: true });
  it("only Cmd/Ctrl+K means anything", () => {
    expect(keyIntent(ev("k", { metaKey: true }), hosted)).toEqual({ type: "command" });
    expect(keyIntent(ev("K", { ctrlKey: true }), hosted)).toEqual({ type: "command" });
    for (const k of ["1", "2", "3", "t", "?", "/", "z", "j", "a", "d", "Enter", " ", "ArrowDown", "m", "x", "v"]) expect(keyIntent(ev(k), hosted)).toBeNull();
  });
  it("Escape still reaches the shell — for its own keyboard list and account menu only", () => {
    expect(keyIntent(ev("Escape"), hosted)).toEqual({ type: "escape" });
    expect(escapeStep({ help: true, menu: false, inField: true, hosted: true })).toBe("help");
    expect(escapeStep({ help: false, menu: true, inField: false, hosted: true })).toBe("menu");
  });
  it("Escape never blurs a classic field, and there is no lens to hand it to", () => {
    expect(escapeStep({ help: false, menu: false, inField: true, hosted: true })).toBe("none");
    expect(escapeStep({ help: false, menu: false, inField: false, hosted: true })).toBe("none");
  });
  it("on a lens nothing changed", () => {
    expect(keyIntent(ev("1"), ctx({ hosted: false }))).toEqual({ type: "lens", lens: "decide" });
    expect(escapeStep({ help: false, menu: false, inField: true, hosted: false })).toBe("blur");
  });
});
