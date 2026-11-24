import type { Lens } from "./keys";
import { pageTitle } from "./story";

/** The lens tab an address belongs to. «经过» (story) is a page of the lens it was opened from, «待决» unless said.
 *  null = no lens: a classic page hosted under the frame, or a NewUI page that is not one of the three (round 3 —
 *  until then every other address answered «待决», and its tab showed selected over whatever was on the page). */
export function lensOf(pathname: string, from: unknown): Lens | null {
  const m = /^\/app\/new\/(decide|live|world|story)(\/|$)/.exec(pathname);
  if (!m) return null;
  // a story opened from the «all items» table is a page of no lens
  if (m[1] === "story") return from === "items" ? null : from === "live" || from === "world" ? from : "decide";
  return m[1] as Lens;
}

/** The browser tab's title: a story by its item, a lens by itself, a hosted classic page by its section (what the
 *  classic top bar wrote there), anything else the product alone. */
export function shellTitle(pathname: string, w: { lens: string | null; story: string; section: string | null }): string {
  if (w.lens) return pageTitle(pathname, w.lens, w.story);
  return w.section ? `AgenticOps · ${w.section}` : "AgenticOps";
}
