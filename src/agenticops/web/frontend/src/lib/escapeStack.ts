/**
 * Which overlay an Escape key press closes (MVP-2.9.0 N25). The house rule is that every dialog closes on Escape;
 * 13 hand-drawn full-screen overlays of the classic pages did not. One stack for all of them: the overlay opened
 * last is the one that closes; nothing closes when the key was already taken (a Radix dialog on top marks the event
 * handled) or while an input method composes (there Escape cancels the composition). Pure —
 * `hooks/useCloseOnEscape` binds it to the window.
 */
export type Close = () => void;

const open: Close[] = [];

/** An overlay opened: it is the top one now. Returns what to call when it closes (calling it twice is harmless). */
export function openOverlay(close: Close): () => void {
  open.push(close);
  return () => {
    const at = open.lastIndexOf(close);
    if (at >= 0) open.splice(at, 1);
  };
}

export interface KeyLike { key: string; defaultPrevented: boolean; isComposing?: boolean; keyCode?: number }

/** Whether this key press closes the overlay whose close is `mine`. */
export function closesOnEscape(mine: Close, e: KeyLike): boolean {
  if (e.key !== "Escape" || e.defaultPrevented || e.isComposing || e.keyCode === 229) return false;
  return open[open.length - 1] === mine;
}
