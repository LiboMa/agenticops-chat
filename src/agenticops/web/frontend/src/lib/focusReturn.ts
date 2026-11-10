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

/** Where focus goes when a dialog closes: its opener, unless the action removed the opener's row (a deleted user) —
 *  then `fallback`, the page's own button. Decided before the dialog closes: Radix hands focus back while the row is
 *  still on the page, and the refetch that removes it would drop focus on <body> (MVP-2.8.0 T11 E2E). */
export function closeFocusTarget<T>(opener: T | null, fallback: T | null, removed: boolean): T | null {
  return removed && fallback ? fallback : opener;
}
