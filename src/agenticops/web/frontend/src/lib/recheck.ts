/** Run `fn` once at the epoch-ms moment `at` — at once when it has passed. Returns the cancel. */
export function scheduleAt(at: number, fn: () => void, now: number = Date.now()): () => void {
  const h = setTimeout(fn, Math.max(0, at - now));
  return () => clearTimeout(h);
}
