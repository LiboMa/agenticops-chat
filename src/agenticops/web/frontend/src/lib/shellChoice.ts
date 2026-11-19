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

/** The shell that draws an address: NewUI's own addresses are always its own; every other one is the person's choice. */
export function shellFor(pathname: string, choice: Shell): Shell {
  return isNewPath(pathname) ? "new" : choice;
}
