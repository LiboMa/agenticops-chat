import type { ChatSession } from "@/api/types";

export interface SessionGroup {
  label: string;
  sessions: ChatSession[];
}

/**
 * Bucket an ALREADY sorted+filtered session list (from sortSessions/filterArchived)
 * into time groups for rendering. Pinned/Starred take precedence over date.
 * A session appears in exactly one group. Empty groups are omitted. Input order
 * is preserved within each group (so sortSessions' ordering still holds).
 *
 * `now` is injectable for deterministic tests (defaults to Date.now()).
 */
export function groupSessions(
  sessions: ChatSession[],
  now: number = Date.now(),
): SessionGroup[] {
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const todayMs = startOfToday.getTime();
  const dayMs = 86_400_000;

  const buckets: Record<string, ChatSession[]> = {
    Pinned: [],
    Starred: [],
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    "Previous 30 days": [],
    Older: [],
  };

  for (const s of sessions) {
    if (s.pinned) { buckets.Pinned.push(s); continue; }
    if (s.starred) { buckets.Starred.push(s); continue; }
    const t = new Date(s.last_activity_at).getTime();
    if (t >= todayMs) buckets.Today.push(s);
    else if (t >= todayMs - dayMs) buckets.Yesterday.push(s);
    else if (t >= todayMs - 7 * dayMs) buckets["Previous 7 days"].push(s);
    else if (t >= todayMs - 30 * dayMs) buckets["Previous 30 days"].push(s);
    else buckets.Older.push(s);
  }

  const order = ["Pinned", "Starred", "Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];
  return order
    .filter((label) => buckets[label].length > 0)
    .map((label) => ({ label, sessions: buckets[label] }));
}
