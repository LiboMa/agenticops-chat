/** Within this many px of the bottom, a chat follows its newest content. */
export const STICK_PX = 80;

/**
 * Whether the chat keeps following its newest content after a scroll event (2026-11-07). Reaching the bottom always
 * sticks; only a scroll the USER made (wheel, touch, keys, the scrollbar) unsticks it. A scroll nobody made — rows
 * measured taller than estimated (a table, a chart), the virtual list adjusting its offset — must not, or a long
 * chat opens short of its last message.
 */
export function nextStick(stuck: boolean, distanceFromBottom: number, userScrolled: boolean): boolean {
  if (distanceFromBottom < STICK_PX) return true;
  return userScrolled ? false : stuck;
}
