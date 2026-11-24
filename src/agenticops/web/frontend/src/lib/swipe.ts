/** A finished touch swipe as a step (2026-11-07): left = next (+1), right = previous (−1); one that is short or more
 *  vertical than horizontal (a scroll) is nothing (0). */
export function swipeStep(dx: number, dy: number, threshold = 50): -1 | 0 | 1 {
  if (Math.abs(dx) < threshold || Math.abs(dy) > Math.abs(dx)) return 0;
  return dx < 0 ? 1 : -1;
}
