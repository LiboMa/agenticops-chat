/**
 * Property 3: 会话列表排序不变量
 *
 * Feature: chat-session-persistence, Property 3: 会话列表排序不变量
 *
 * Validates: Requirements 3.7
 *
 * For any session list (with any combination of pinned, starred, and normal sessions),
 * the sorted result must satisfy:
 *   - All pinned sessions appear before all starred (non-pinned) sessions
 *   - All starred sessions appear before all normal sessions
 *   - Within each group, sessions are sorted by last_activity_at descending
 */
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { sortSessions, filterArchived } from "@/lib/sortSessions";
import type { ChatSession } from "@/api/types";

/** Generate a random ISO date string from a timestamp range (2020–2030). */
const isoDateArb = fc
  .integer({
    min: new Date("2020-01-01T00:00:00Z").getTime(),
    max: new Date("2030-01-01T00:00:00Z").getTime(),
  })
  .map((ts) => new Date(ts).toISOString());

/** Arbitrary that generates a random ChatSession with random flags and timestamps. */
const chatSessionArb: fc.Arbitrary<ChatSession> = fc
  .record({
    id: fc.integer({ min: 1, max: 100_000 }),
    session_id: fc.uuid(),
    name: fc.string({ minLength: 1, maxLength: 50 }),
    created_at: isoDateArb,
    updated_at: isoDateArb,
    last_activity_at: isoDateArb,
    message_count: fc.integer({ min: 0, max: 1000 }),
    pinned: fc.boolean(),
    starred: fc.boolean(),
    archived: fc.boolean(),
  });

function tier(s: ChatSession): number {
  return s.pinned ? 2 : s.starred ? 1 : 0;
}

describe("Feature: chat-session-persistence, Property 3: 会话列表排序不变量", () => {
  it("pinned sessions appear before starred, starred before normal, and within-group order is by last_activity_at desc", () => {
    fc.assert(
      fc.property(
        fc.array(chatSessionArb, { minLength: 0, maxLength: 30 }),
        (sessions) => {
          const sorted = sortSessions(sessions);

          // 1. All pinned before all starred (non-pinned), all starred before normal
          for (let i = 0; i < sorted.length; i++) {
            for (let j = i + 1; j < sorted.length; j++) {
              expect(tier(sorted[i])).toBeGreaterThanOrEqual(tier(sorted[j]));
            }
          }

          // 2. Within each tier, last_activity_at is descending
          for (let i = 0; i < sorted.length - 1; i++) {
            if (tier(sorted[i]) === tier(sorted[i + 1])) {
              const timeA = new Date(sorted[i].last_activity_at).getTime();
              const timeB = new Date(sorted[i + 1].last_activity_at).getTime();
              expect(timeA).toBeGreaterThanOrEqual(timeB);
            }
          }
        },
      ),
      { numRuns: 200 },
    );
  });
});


/**
 * Property 4: 归档会话默认隐藏
 *
 * Feature: chat-session-persistence, Property 4: 归档会话默认隐藏
 *
 * Validates: Requirements 3.9
 *
 * For any session list, filtering with showArchived=false (default behavior)
 * must never include any session with archived === true.
 */
describe("Feature: chat-session-persistence, Property 4: 归档会话默认隐藏", () => {
  it("filterArchived(sessions, false) never includes archived sessions", () => {
    fc.assert(
      fc.property(
        fc.array(chatSessionArb, { minLength: 0, maxLength: 30 }),
        (sessions) => {
          const filtered = filterArchived(sessions, false);

          // No session in the result should be archived
          for (const s of filtered) {
            expect(s.archived).toBe(false);
          }

          // All non-archived sessions from the input should be present
          const nonArchived = sessions.filter((s) => !s.archived);
          expect(filtered).toHaveLength(nonArchived.length);
        },
      ),
      { numRuns: 200 },
    );
  });
});
