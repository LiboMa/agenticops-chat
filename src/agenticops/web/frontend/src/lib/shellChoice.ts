/**
 * Which interface a person uses (MVP-2.9.0 round 3): the classic workspace or NewUI's shell around every page.
 * Their own choice, per user in this browser — like the theme, the font size and the account scope — and read
 * synchronously, so the right shell paints first. The classic one is the default. Pure, so node can test it.
 */
import { currentUserId, userKey } from "@/lib/home";

export type Shell = "classic" | "new";

const BASE = "aiops-shell";
export const shellKey = (userId: number | null | undefined) => userKey(BASE, userId);

/** A stored value, read: only the word «new» is the new interface. */
export function choiceOf(stored: unknown): Shell {
  return stored === "new" ? "new" : "classic";
}

export function readChoice(userId: number | null = currentUserId()): Shell {
  try {
    return choiceOf(localStorage.getItem(shellKey(userId)));
  } catch {
    return "classic";
  }
}

export function setChoice(shell: Shell, userId: number | null = currentUserId()): void {
  try {
    if (shell === "new") localStorage.setItem(shellKey(userId), "new");
    else localStorage.removeItem(shellKey(userId));
  } catch { /* private mode: the choice lasts as long as the address says so */ }
}

/** NewUI's own addresses (/app/new and below). */
export const isNewPath = (pathname: string): boolean => /^\/app\/new(\/|$)/.test(pathname);

/** The router state of «back to the classic interface» (`navigate("/app", { state: TO_CLASSIC })`). */
export const TO_CLASSIC = { shell: "classic" } as const;

/** Whether a navigation is that way out of NewUI's frame. */
export function leavesNew(state: unknown): boolean {
  return !!state && typeof state === "object" && (state as { shell?: unknown }).shell === "classic";
}

/** The shell that draws an address: NewUI's own addresses are always its own; every other one is the person's
 *  choice — or the frame they are already in. `was` = the shell that drew the address they come from in this tab:
 *  someone in NewUI by its address alone (a bookmark from before round 3, a link a colleague sent — nothing is
 *  stored for them) stays in its frame when they go on to a page. The «pages» menu used to open the classic shell
 *  under their feet, and a decision inside its undo window was sent as the frame went away (MVP-2.9.0 N27,
 *  review). «Back to classic» is the way out (`leaving`, lib/shellChoice.leavesNew). */
export function shellFor(pathname: string, choice: Shell, was: Shell | null = null, leaving = false): Shell {
  if (isNewPath(pathname)) return "new";
  if (leaving) return "classic";
  return choice === "new" || was === "new" ? "new" : "classic";
}
