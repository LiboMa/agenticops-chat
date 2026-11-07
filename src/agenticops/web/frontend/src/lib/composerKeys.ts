export interface KeyLike {
  key: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  isComposing: boolean;
  keyCode?: number;
}

/** Whether a key press in the composer sends (2026-11-07): Enter on desktop, Shift+Enter a newline; on a touch screen
 *  Enter is a newline (the send button sends, as in mobile chat apps); Cmd/Ctrl+Enter always sends. Never while an
 *  input method is composing — Enter then picks a candidate (Safari reports that as keyCode 229). */
export function shouldSend(e: KeyLike, coarsePointer: boolean): boolean {
  if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return false;
  if (e.metaKey || e.ctrlKey) return true;
  if (e.shiftKey || coarsePointer) return false;
  return true;
}
