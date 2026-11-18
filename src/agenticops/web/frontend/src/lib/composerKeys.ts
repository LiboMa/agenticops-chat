export interface KeyLike {
  key: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  isComposing: boolean;
  keyCode?: number;
}

/** An input method is composing (Chinese / Japanese candidates): its Enter picks a candidate, never an action.
 *  Safari reports that Enter as keyCode 229. */
export function isComposingKey(e: Pick<KeyLike, "isComposing" | "keyCode">): boolean {
  return e.isComposing || e.keyCode === 229;
}

/** For a single-line field inside a <form> (the browser submits the form on Enter): keep the Enter that picks an
 *  input method's candidate from submitting it. While a composition is going on (`isComposing`) Chrome and Firefox
 *  keep that Enter to the input method and submit nothing — the key is recognised here and left alone: cancelling a
 *  key the input method is still handling is not ours to do. Safari ends the composition first and THEN delivers
 *  the key (keyCode 229, isComposing false) — and would submit a half-typed sentence: that one is cancelled.
 *  Call from the field's onKeyDown; true = it was an input method's Enter. */
export function keepsImeEnter(e: { key: string; preventDefault: () => void; nativeEvent: Pick<KeyLike, "isComposing" | "keyCode"> }): boolean {
  if (e.key !== "Enter" || !isComposingKey(e.nativeEvent)) return false;
  if (!e.nativeEvent.isComposing) e.preventDefault();
  return true;
}

/** Whether a key press in the composer sends (2026-11-07): Enter on desktop, Shift+Enter a newline; on a touch screen
 *  Enter is a newline (the send button sends, as in mobile chat apps); Cmd/Ctrl+Enter always sends. Never while an
 *  input method is composing — Enter then picks a candidate (Safari reports that as keyCode 229). */
export function shouldSend(e: KeyLike, coarsePointer: boolean): boolean {
  if (e.key !== "Enter" || isComposingKey(e)) return false;
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
