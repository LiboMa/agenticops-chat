/**
 * The conversation list's logic (MVP-2.9.0 N22 — the 2.8.0 spec's S5). The server filters, searches, orders and
 * cuts; this module asks for a page, groups what came by UTC day, and says what a row shows. Pure, so node can
 * test it.
 */
import type { InfiniteData } from "@tanstack/react-query";
import type { ChatSession, ChatSessionPage } from "@/api/types";
import { parseApiDate } from "@/lib/formatDate";

export type SessionView = "all" | "starred" | "archived";
export const SESSION_VIEWS: readonly SessionView[] = ["all", "starred", "archived"];
export const SESSIONS_PAGE = 50;

/** The request for one page (apiFetch path): the view, the search, the cursor the page before handed over. */
export function sessionsRequest(view: SessionView, q: string, cursor: string | null): string {
  const params = new URLSearchParams({ view, limit: String(SESSIONS_PAGE) });
  if (q.trim()) params.set("q", q.trim());
  if (cursor) params.set("cursor", cursor);
  return `/chat/sessions?${params.toString()}`;
}

export type GroupKey = "pinned" | "today" | "yesterday" | "week" | "older";
const ORDER: GroupKey[] = ["pinned", "today", "yesterday", "week", "older"];
const DAY = 86_400_000;

/** The list in groups — pinned, then by the UTC day of the last activity: today, yesterday, earlier this week
 *  (Monday first), older. The order inside a group is the list's own (the server's); an empty group is left out.
 *  Starred is a tab, not a group. */
export function sessionGroups(sessions: ChatSession[], now: number = Date.now()): { key: GroupKey; sessions: ChatSession[] }[] {
  const today = Math.floor(now / DAY) * DAY;                                      // 00:00 UTC of today
  const monday = today - ((new Date(today).getUTCDay() + 6) % 7) * DAY;           // 00:00 UTC of this week's Monday
  const buckets: Record<GroupKey, ChatSession[]> = { pinned: [], today: [], yesterday: [], week: [], older: [] };
  for (const s of sessions) {
    const at = parseApiDate(s.last_activity_at)?.getTime() ?? 0;
    const key: GroupKey = s.pinned ? "pinned" : at >= today ? "today" : at >= today - DAY ? "yesterday" : at >= monday ? "week" : "older";
    buckets[key].push(s);
  }
  return ORDER.filter((key) => buckets[key].length > 0).map((key) => ({ key, sessions: buckets[key] }));
}

/** The one thing a row says is going on, the most pressing first: a reply being written (here, or as the server
 *  knows), the item it is about waiting on you, the last send not finished, a tool of the last reply failed. */
export function activityKey(s: Pick<ChatSession, "activity" | "waiting_on_you">, streamingHere: boolean): string | null {
  if (streamingHere || s.activity === "generating") return "chat.activity.generating";
  if (s.waiting_on_you) return "chat.activity.waiting";
  if (s.activity === "failed") return "chat.activity.failed";
  if (s.activity === "tool_failed") return "chat.activity.toolFailed";
  return null;
}

/** «just now» / «N minutes ago» / «N hours ago» / «N days ago» as a locale key and its number. */
export function agoParts(iso: string, now: number = Date.now()): { key: string; n: number } {
  const at = parseApiDate(iso)?.getTime() ?? now;
  const minutes = Math.floor((now - at) / 60_000);
  if (minutes < 1) return { key: "chat.ago.now", n: 0 };
  if (minutes < 60) return { key: "chat.ago.minutes", n: minutes };
  if (minutes < 60 * 24) return { key: "chat.ago.hours", n: Math.floor(minutes / 60) };
  return { key: "chat.ago.days", n: Math.floor(minutes / (60 * 24)) };
}

export type MenuAction = "rename" | "pin" | "star" | "archive" | "visibility" | "delete";

/** The ⋯ menu of a row, in this order — delete last. Empty for someone who may not manage the conversation;
 *  sharing only for its owner, signed in. */
export function menuActions(s: Pick<ChatSession, "pinned" | "starred" | "archived" | "visibility" | "owned_by_me" | "can_manage">,
                            authenticated: boolean): { id: MenuAction; labelKey: string }[] {
  if (s.can_manage === false) return [];
  const actions: { id: MenuAction; labelKey: string }[] = [
    { id: "rename", labelKey: "chat.rename" },
    { id: "pin", labelKey: s.pinned ? "chat.unpin" : "chat.pin" },
    { id: "star", labelKey: s.starred ? "chat.unstar" : "chat.star" },
    { id: "archive", labelKey: s.archived ? "chat.unarchive" : "chat.archive" },
  ];
  if (authenticated && s.owned_by_me) actions.push({ id: "visibility", labelKey: s.visibility === "private" ? "chat.makeWorkspace" : "chat.makePrivate" });
  actions.push({ id: "delete", labelKey: "common.delete" });
  return actions;
}

/** The conversation to open after `deletedId` is deleted: the next one down, the one above when it was the last,
 *  null (the welcome page) when it was the only one or is not on the list. */
export function nextAfterDelete(rows: Pick<ChatSession, "session_id">[], deletedId: string): string | null {
  const at = rows.findIndex((s) => s.session_id === deletedId);
  if (at < 0) return null;
  return (rows[at + 1] ?? rows[at - 1])?.session_id ?? null;
}

/** The line under the list: how many there are — and how many match, when something is searched. */
export function countsLine(q: string, total: number, allTotal: number): { key: string; vars: Record<string, number> } {
  return q.trim() ? { key: "chat.count.matched", vars: { n: total, total: allTotal } } : { key: "chat.count.all", vars: { total: allTotal } };
}

export type SessionListData = InfiniteData<ChatSessionPage, string | null>;

/** One row changed (renamed by the server, say): the same change in a loaded list, at once. The same object when
 *  the row is not in it. */
export function patchSessionPages(data: SessionListData | undefined, sessionId: string, patch: Partial<ChatSession>): SessionListData | undefined {
  if (!data || !data.pages.some((p) => p.items.some((s) => s.session_id === sessionId))) return data;
  return {
    ...data,
    pages: data.pages.map((p) => (p.items.some((s) => s.session_id === sessionId)
      ? { ...p, items: p.items.map((s) => (s.session_id === sessionId ? { ...s, ...patch } : s)) } : p)),
  };
}
