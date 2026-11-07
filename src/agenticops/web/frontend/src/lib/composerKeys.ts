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

/** What a drag over the chat does (2026-11-07): a FILE drag is always taken from the browser (left alone, the browser
 *  would open the file in the tab and leave the app, cutting a reply that is streaming); its files are attached only
 *  while the composer is enabled. A text-selection drag is left alone. */
export function fileDragAction(types: readonly string[] | undefined, disabled: boolean): { prevent: boolean; accept: boolean } {
  const files = !!types && Array.from(types).includes("Files");
  return { prevent: files, accept: files && !disabled };
}
