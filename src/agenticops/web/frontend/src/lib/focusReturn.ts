/** Radix Dialog returns focus only to its own `Dialog.Trigger`. A dialog opened from any other button keeps the
 *  element that had focus when it opened and hands focus back to it in `onCloseAutoFocus` (MVP-2.8.0 S2 — the
 *  CommandPalette does the same since S1). An opener no longer on the page is left to Radix. */
export function returnFocusTo(
  opener: { isConnected: boolean; focus: () => void } | null,
  event: { preventDefault: () => void },
): void {
  if (!opener?.isConnected) return;
  event.preventDefault();
  opener.focus();
}
