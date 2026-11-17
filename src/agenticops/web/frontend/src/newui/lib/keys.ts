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
  if (ctx.inField || ctx.modal || !ctx.singleKeys) return null;
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
