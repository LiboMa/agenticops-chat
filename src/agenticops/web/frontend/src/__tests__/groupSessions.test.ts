import { describe, it, expect } from "vitest";
import { groupSessions } from "@/lib/groupSessions";
import type { ChatSession } from "@/api/types";

// Fixed "now": 2026-06-03T12:00:00Z
const NOW = new Date("2026-06-03T12:00:00Z").getTime();

function sess(over: Partial<ChatSession> & { session_id: string; last_activity_at: string }): ChatSession {
  return {
    id: 1,
    name: "s",
    created_at: over.last_activity_at,
    updated_at: over.last_activity_at,
    message_count: 0,
    pinned: false,
    starred: false,
    archived: false,
    ...over,
  } as ChatSession;
}

describe("groupSessions", () => {
  it("buckets by date relative to the injected now", () => {
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const yesterday = sess({ session_id: "y", last_activity_at: "2026-06-02T09:00:00Z" });
    const week = sess({ session_id: "w", last_activity_at: "2026-05-30T09:00:00Z" });
    const month = sess({ session_id: "m", last_activity_at: "2026-05-20T09:00:00Z" });
    const old = sess({ session_id: "o", last_activity_at: "2026-01-01T09:00:00Z" });
    const groups = groupSessions([today, yesterday, week, month, old], NOW);
    const labels = groups.map((g) => g.label);
    expect(labels).toEqual(["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]);
  });

  it("pinned and starred take precedence over date", () => {
    const pinnedOld = sess({ session_id: "p", last_activity_at: "2026-01-01T00:00:00Z", pinned: true });
    const starredOld = sess({ session_id: "st", last_activity_at: "2026-01-01T00:00:00Z", starred: true });
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const groups = groupSessions([pinnedOld, starredOld, today], NOW);
    expect(groups.map((g) => g.label)).toEqual(["Pinned", "Starred", "Today"]);
    expect(groups[0].sessions[0].session_id).toBe("p");
    expect(groups[1].sessions[0].session_id).toBe("st");
  });

  it("omits empty groups", () => {
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const groups = groupSessions([today], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Today");
  });

  it("each session appears in exactly one group", () => {
    const list = [
      sess({ session_id: "a", last_activity_at: "2026-06-03T09:00:00Z", pinned: true }),
      sess({ session_id: "b", last_activity_at: "2026-06-03T09:00:00Z" }),
      sess({ session_id: "c", last_activity_at: "2026-05-01T09:00:00Z" }),
    ];
    const groups = groupSessions(list, NOW);
    const total = groups.reduce((n, g) => n + g.sessions.length, 0);
    expect(total).toBe(3);
  });

  it("preserves input order within a group", () => {
    const a = sess({ session_id: "a", last_activity_at: "2026-06-03T11:00:00Z" });
    const b = sess({ session_id: "b", last_activity_at: "2026-06-03T08:00:00Z" });
    const groups = groupSessions([a, b], NOW); // already sorted by caller
    expect(groups[0].sessions.map((s) => s.session_id)).toEqual(["a", "b"]);
  });

  it("empty input → empty array", () => {
    expect(groupSessions([], NOW)).toEqual([]);
  });
});
