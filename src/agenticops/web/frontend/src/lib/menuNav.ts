export type MenuKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

/** The menu item a key moves the focus to: one step down / up (wrapping), the first / last; disabled items are
 *  skipped. `current` -1 = no item focused. -1 when no item is enabled. */
export function nextMenuIndex(current: number, key: MenuKey, disabled: readonly boolean[]): number {
  const enabled = disabled.flatMap((d, i) => (d ? [] : [i]));
  if (enabled.length === 0) return -1;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled[enabled.length - 1];
  const at = enabled.indexOf(current);
  if (at === -1) return key === "ArrowDown" ? enabled[0] : enabled[enabled.length - 1];
  const step = key === "ArrowDown" ? 1 : -1;
  return enabled[(at + step + enabled.length) % enabled.length];
}
