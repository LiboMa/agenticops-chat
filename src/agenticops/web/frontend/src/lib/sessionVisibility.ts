import type { ChatSession } from "@/api/types";

export type SessionVisibility = "private" | "workspace";

/** The tag a session row carries for a logged-in reader: `workspace` (everyone sees it) or `othersPrivate`
 *  (someone else's private session — only an admin is shown those). The reader's own private session needs
 *  no tag. With auth off every session is a workspace session, so nothing is tagged. */
export function visibilityTag(s: Pick<ChatSession, "visibility" | "owned_by_me">, authenticated: boolean):
  "workspace" | "othersPrivate" | null {
  if (!authenticated) return null;
  if ((s.visibility ?? "workspace") === "workspace") return "workspace";
  return s.owned_by_me ? null : "othersPrivate";
}

/** Only the owner changes who sees a session from here (the API also lets an admin). */
export function canChangeVisibility(s: Pick<ChatSession, "owned_by_me">, authenticated: boolean): boolean {
  return authenticated && !!s.owned_by_me;
}

export function otherVisibility(s: Pick<ChatSession, "visibility">): SessionVisibility {
  return (s.visibility ?? "workspace") === "private" ? "workspace" : "private";
}
