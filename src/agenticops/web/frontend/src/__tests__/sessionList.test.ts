import { describe, expect, it } from "vitest";
import {
  SESSIONS_PAGE, activityKey, agoParts, countsLine, menuActions, nextAfterDelete, patchSessionPages,
  sessionGroups, sessionsRequest, type SessionListData,
} from "@/lib/sessionList";
import type { ChatSession, ChatSessionPage } from "@/api/types";

const row = (o: Partial<ChatSession> = {}): ChatSession => ({
  id: 1, session_id: "a", name: "s", created_at: "2026-11-19T10:00:00Z", updated_at: "2026-11-19T10:00:00Z",
  last_activity_at: "2026-11-19T10:00:00Z", message_count: 0, pinned: false, starred: false, archived: false,
  model_id: null, can_manage: true, owned_by_me: true, visibility: "private", activity: null, waiting_on_you: false, ...o,
});

describe("the request for one page of conversations", () => {
  it("names the view, and the search and the cursor when there are any", () => {
    expect(sessionsRequest("all", "", null)).toBe(`/chat/sessions?view=all&limit=${SESSIONS_PAGE}`);
    expect(sessionsRequest("archived", " 100% ", "50")).toBe(`/chat/sessions?view=archived&limit=${SESSIONS_PAGE}&q=100%25&cursor=50`);
  });
});

describe("the list in groups, by UTC day", () => {
  // Thursday 2026-11-19, 01:00 UTC — a browser east of Greenwich is already well into its own day
  const now = Date.parse("2026-11-19T01:00:00Z");
  const at = (iso: string, o: Partial<ChatSession> = {}) => row({ session_id: iso, last_activity_at: iso, ...o });
  it("pinned first, then today / yesterday / this week / older — the server's order kept inside each", () => {
    const rows = [
      at("2026-10-01T00:00:00Z", { pinned: true }),
      at("2026-11-19T00:30:00Z"), at("2026-11-19T00:00:00Z"),
      at("2026-11-18T23:59:59Z"),
      at("2026-11-17T12:00:00Z"), at("2026-11-16T00:00:00Z"),      // Tuesday, Monday: this ISO week
      at("2026-11-15T23:59:59Z"),                                    // Sunday: last week
      at("2026-01-01T00:00:00Z"),
    ];
    expect(sessionGroups(rows, now).map((g) => [g.key, g.sessions.map((s) => s.session_id)])).toEqual([
      ["pinned", ["2026-10-01T00:00:00Z"]],
      ["today", ["2026-11-19T00:30:00Z", "2026-11-19T00:00:00Z"]],
      ["yesterday", ["2026-11-18T23:59:59Z"]],
      ["week", ["2026-11-17T12:00:00Z", "2026-11-16T00:00:00Z"]],
      ["older", ["2026-11-15T23:59:59Z", "2026-01-01T00:00:00Z"]],
    ]);
  });
  it("a starred conversation is grouped by its day (starred is a tab, not a group); an empty group is left out", () => {
    expect(sessionGroups([at("2026-11-19T00:10:00Z", { starred: true })], now).map((g) => g.key)).toEqual(["today"]);
    expect(sessionGroups([], now)).toEqual([]);
  });
  it("on a Monday «this week» is empty: Sunday is yesterday", () => {
    const monday = Date.parse("2026-11-16T08:00:00Z");
    expect(sessionGroups([at("2026-11-15T10:00:00Z"), at("2026-11-14T10:00:00Z")], monday).map((g) => g.key)).toEqual(["yesterday", "older"]);
  });
});

describe("what a row says is going on", () => {
  it("one line, the most pressing first", () => {
    expect(activityKey(row(), false)).toBeNull();
    expect(activityKey(row({ activity: "tool_failed" }), false)).toBe("chat.activity.toolFailed");
    expect(activityKey(row({ activity: "failed" }), false)).toBe("chat.activity.failed");
    expect(activityKey(row({ waiting_on_you: true, activity: "tool_failed" }), false)).toBe("chat.activity.waiting");
    expect(activityKey(row({ waiting_on_you: true, activity: "generating" }), false)).toBe("chat.activity.generating");
  });
  it("a reply streaming in THIS tab is generating, whatever the list last heard", () => {
    expect(activityKey(row({ activity: "failed" }), true)).toBe("chat.activity.generating");
  });
});

describe("how long ago", () => {
  const now = Date.parse("2026-11-19T12:00:00Z");
  it.each([
    ["2026-11-19T11:59:40Z", { key: "chat.ago.now", n: 0 }],
    ["2026-11-19T11:15:00Z", { key: "chat.ago.minutes", n: 45 }],
    ["2026-11-19T07:00:00Z", { key: "chat.ago.hours", n: 5 }],
    ["2026-11-16T12:00:00Z", { key: "chat.ago.days", n: 3 }],
    ["2026-11-19T13:00:00Z", { key: "chat.ago.now", n: 0 }],          // a clock ahead of ours is «just now», never negative
  ])("%s", (iso, want) => expect(agoParts(iso, now)).toEqual(want));
  it("reads a time without a zone as UTC (the API's older fields)", () => {
    expect(agoParts("2026-11-19T11:00:00", now)).toEqual({ key: "chat.ago.hours", n: 1 });
  });
});

describe("the ⋯ menu", () => {
  it("is in this order, delete last; the words follow the row's state", () => {
    expect(menuActions(row(), true).map((a) => [a.id, a.labelKey])).toEqual([
      ["rename", "chat.rename"], ["pin", "chat.pin"], ["star", "chat.star"], ["archive", "chat.archive"],
      ["visibility", "chat.makeWorkspace"], ["delete", "common.delete"],
    ]);
    expect(menuActions(row({ pinned: true, starred: true, archived: true, visibility: "workspace" }), true).map((a) => a.labelKey)).toEqual([
      "chat.rename", "chat.unpin", "chat.unstar", "chat.unarchive", "chat.makePrivate", "common.delete",
    ]);
  });
  it("offers sharing only to its owner, signed in; and nothing to someone who may not manage it", () => {
    expect(menuActions(row({ owned_by_me: false }), true).map((a) => a.id)).not.toContain("visibility");
    expect(menuActions(row(), false).map((a) => a.id)).not.toContain("visibility");
    expect(menuActions(row({ can_manage: false }), true)).toEqual([]);
  });
});

describe("after a conversation is deleted", () => {
  const rows = [row({ session_id: "a" }), row({ session_id: "b" }), row({ session_id: "c" })];
  it("the next one down is opened — the one above when it was the last", () => {
    expect(nextAfterDelete(rows, "b")).toBe("c");
    expect(nextAfterDelete(rows, "c")).toBe("b");
  });
  it("the welcome page when it was the only one, or was not on the list", () => {
    expect(nextAfterDelete([rows[0]], "a")).toBeNull();
    expect(nextAfterDelete(rows, "zzz")).toBeNull();
  });
});

describe("the counts under the list", () => {
  it("says how many match only when something is searched", () => {
    expect(countsLine("", 12, 12)).toEqual({ key: "chat.count.all", vars: { total: 12 } });
    expect(countsLine("nginx", 3, 12)).toEqual({ key: "chat.count.matched", vars: { n: 3, total: 12 } });
    expect(countsLine("a", 12, 12)).toEqual({ key: "chat.count.matched", vars: { n: 12, total: 12 } });   // a search that matches them all is still a search
  });
});

describe("a change shown at once in every loaded list", () => {
  const page = (items: ChatSession[]): ChatSessionPage => ({ items, total: items.length, all_total: items.length, next_cursor: null });
  const data: SessionListData = { pages: [page([row({ session_id: "a" }), row({ session_id: "b", name: "old" })]), page([row({ session_id: "c" })])], pageParams: [null, "2"] };
  it("patches the one row and leaves the rest as they were", () => {
    const next = patchSessionPages(data, "b", { name: "new" });
    expect(next?.pages[0].items.map((s) => s.name)).toEqual(["s", "new"]);
    expect(next?.pages[1]).toBe(data.pages[1]);
    expect(next?.pageParams).toBe(data.pageParams);
  });
  it("is the same object when the row is not there; nothing for no data", () => {
    expect(patchSessionPages(data, "zzz", { name: "x" })).toBe(data);
    expect(patchSessionPages(undefined, "a", { name: "x" })).toBeUndefined();
  });
});
