import type { ChatSession } from "@/api/types";

/**
 * Sort sessions by priority: pinned → starred → normal.
 * Within each group, sort by last_activity_at descending.
 *
 * Validates: Requirements 3.7
 */
export function sortSessions(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort((a, b) => {
    // Priority tier: pinned = 2, starred = 1, normal = 0
    const tierA = a.pinned ? 2 : a.starred ? 1 : 0;
    const tierB = b.pinned ? 2 : b.starred ? 1 : 0;
    if (tierA !== tierB) return tierB - tierA;
    // Within same tier, sort by last_activity_at descending
    return (
      new Date(b.last_activity_at).getTime() -
      new Date(a.last_activity_at).getTime()
    );
  });
}

/**
 * Filter out archived sessions (default behavior).
 *
 * Validates: Requirements 3.9
 */
export function filterArchived(
  sessions: ChatSession[],
  showArchived: boolean,
): ChatSession[] {
  if (showArchived) return sessions;
  return sessions.filter((s) => !s.archived);
}
