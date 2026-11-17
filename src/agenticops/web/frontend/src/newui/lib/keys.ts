import { isComposingKey } from "@/lib/composerKeys";

/** What a key press means in NewUI. One rule for every lens, so a letter typed into a field, a candidate picked in an
 *  input method, or a browser shortcut never turns into a decision. */
export interface KeyEventLike {
  key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; repeat: boolean;
  isComposing: boolean; keyCode?: number;
}

export interface KeyContext {
  /** the focus is where typing goes: an input, a textarea, a select, editable text */
  inField: boolean;
  /** the focus is on a button or a link: Space and Enter press it */
  onControl: boolean;
  /** a dialog or a menu is open: it owns the keyboard, Escape closes it */
  modal: boolean;
  /** single-key shortcuts are on (the person can switch them off — WCAG 2.1.4) */
  singleKeys: boolean;
  /** a key went into a field a moment ago: the field may have gone away under the hands, the typing has not */
  typing?: boolean;
}

export type Lens = "decide" | "live" | "world";
export type KeyIntent =
  | { type: "escape" }
  | { type: "command" }
  | { type: "help" }
  | { type: "theme" }
  | { type: "lens"; lens: Lens }
  | { type: "lensKey"; key: string; repeat: boolean };

const LENS_KEYS: Record<string, Lens> = { "1": "decide", "2": "live", "3": "world" };

export function keyIntent(e: KeyEventLike, ctx: KeyContext): KeyIntent | null {
  if (isComposingKey(e) || e.key === "Process") return null;
  const key = e.key.toLowerCase();
  if (key === "escape") return { type: "escape" };
  if ((e.metaKey || e.ctrlKey) && !e.altKey && key === "k") return { type: "command" };
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  if (ctx.inField || ctx.typing || ctx.modal || !ctx.singleKeys) return null;
  if ((key === " " || key === "enter") && ctx.onControl) return null;
  if (key === "/") return { type: "command" };
  if (key === "?") return { type: "help" };
  if (key === "t") return { type: "theme" };
  if (LENS_KEYS[key]) return { type: "lens", lens: LENS_KEYS[key] };
  return { type: "lensKey", key, repeat: e.repeat };
}

/** Reads the context off the page: where the focus is. `modal` and `singleKeys` are the shell's own state. */
export function focusContext(active: Element | null): Pick<KeyContext, "inField" | "onControl"> {
  const tag = active?.tagName ?? "";
  const editable = !!active && (active as HTMLElement).isContentEditable === true;
  return {
    inField: /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || editable,
    onControl: /^(BUTTON|A|SUMMARY)$/.test(tag) || active?.getAttribute?.("role") === "button",
  };
}

/** What Escape does, one layer at a time: the keyboard list, the account menu — then, while the person is typing,
 *  it only leaves the field (a page must not close, nor an open resource, under their hands; a field that owns its
 *  Escape — a reason box, the command bar — handles it before it gets here) — and only then is it the lens's. */
export function escapeStep(s: { help: boolean; menu: boolean; inField: boolean }): "help" | "menu" | "blur" | "lens" {
  return s.help ? "help" : s.menu ? "menu" : s.inField ? "blur" : "lens";
}

/** A reason box can disappear mid-sentence — a colleague decided the item, the 30-second refresh replaced the page —
 *  and the next letters would be single-key decisions on a page the person has not read. So for a moment after a key
 *  went into a field, keys are still typing; each key swallowed that way renews the moment. */
export const TYPING_GRACE_MS = 1000;
export function stillTyping(lastFieldKeyAt: number | null, now: number): boolean {
  return lastFieldKeyAt !== null && now - lastFieldKeyAt < TYPING_GRACE_MS;
}

/** The keys that send or leave a field end the typing at once: J right after a reason was sent must work. */
export function endsTyping(key: string): boolean {
  return key === "Enter" || key === "Escape" || key === "Tab";
}

/** How long a toast stays: long enough to read it. A short line 2.6 s; a long refusal up to 9 s. */
export function toastMs(text: string): number {
  return Math.min(9000, Math.max(2600, text.length * 70));
}

/** A brief that came onto the page without the person opening it — the item was decided elsewhere, changed
 *  situation, or a decision moved the page on — does not take keys at once: the second press of a key meant for the
 *  page before must not be this page's main action. Returns until when the brief's keys wait; null = no wait (the
 *  person's own J / K / click, the first page, no change). */
export const SWAP_GUARD_MS = 600;
export function swapGuard(prev: string | null, next: string, ownMove: boolean, now: number): number | null {
  return prev === null || prev === next || ownMove ? null : now + SWAP_GUARD_MS;
}

