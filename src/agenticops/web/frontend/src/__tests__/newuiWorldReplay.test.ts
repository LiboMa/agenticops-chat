import { describe, expect, it } from "vitest";
import { REPLAY_MS, STEP_MS, atOf, jump, moments, playPlan, valueOf } from "@/newui/lib/world/replay";

const NOW = Date.parse("2026-11-18T12:00:00Z");
const at = (hoursAgo: number) => NOW - hoursAgo * 3_600_000;
const iso = (hoursAgo: number) => new Date(at(hoursAgo)).toISOString();

describe("the slider — a moment of the last 24 hours, in five-minute steps", () => {
  it("the right end is now, the left end is 24 hours ago", () => {
    const max = REPLAY_MS / STEP_MS;
    expect(max).toBe(288);
    expect(atOf(max, NOW)).toBeNull();                   // the right end is «now», not a moment in the past
    expect(atOf(0, NOW)).toBe(NOW - REPLAY_MS);
    expect(atOf(max - 1, NOW)).toBe(NOW - STEP_MS);
    expect(valueOf(null, NOW)).toBe(max);
    expect(valueOf(NOW - STEP_MS, NOW)).toBe(max - 1);
  });

  it("a moment between two steps reads as the nearer one, and nothing leaves the day", () => {
    expect(valueOf(NOW - STEP_MS - 1000, NOW)).toBe(287);          // a second older than a step: still that step
    expect(valueOf(NOW - STEP_MS - 151_000, NOW)).toBe(286);       // past the middle: the step before
    expect(valueOf(NOW - REPLAY_MS - 5_000_000, NOW)).toBe(0);
    expect(valueOf(NOW + 60_000, NOW)).toBe(288);
    expect(atOf(-3, NOW)).toBe(NOW - REPLAY_MS);
    expect(atOf(999, NOW)).toBeNull();
  });
});

describe("the slider does not creep while the clock runs", () => {
  it("a moment picked on a step is still on that step a second later", () => {
    // found in the browser: one ArrowLeft moved the slider two steps — the moment was read back against a clock one
    // second on, fell just short of its step, and was floored to the one before
    const picked = atOf(287, NOW)!;
    expect(valueOf(picked, NOW + 1000)).toBe(287);
    expect(valueOf(picked, NOW + 120_000)).toBe(287);
    expect(valueOf(picked, NOW + 160_000)).toBe(286);              // 2 min 40 s on: it IS nearer the step before now
  });
});

describe("moments — the times at which something happened, each once", () => {
  it("are the events' own times, oldest first, a minute at most once, outside the day left out", () => {
    const events = [{ at: iso(5) }, { at: new Date(at(5) + 20_000).toISOString() }, { at: iso(2) }, { at: iso(30) }, { at: "nonsense" }, { at: iso(-1) }];
    expect(moments(events, NOW)).toEqual([at(5), at(2)]);
  });

  it("is empty for no answer", () => {
    expect(moments(undefined, NOW)).toEqual([]);
  });
});

describe("jump — [ and ]: to the event before, to the event after", () => {
  const ms = [at(8), at(5), at(2)];

  it("from now, back goes to the newest event; forward stays at now", () => {
    expect(jump(ms, null, -1)).toBe(at(2));
    expect(jump(ms, null, 1)).toBeNull();
  });

  it("walks the events in order and returns to now after the newest", () => {
    expect(jump(ms, at(2), -1)).toBe(at(5));
    expect(jump(ms, at(5), -1)).toBe(at(8));
    expect(jump(ms, at(8), -1)).toBe(at(8));            // nothing older: stays
    expect(jump(ms, at(8), 1)).toBe(at(5));
    expect(jump(ms, at(2), 1)).toBeNull();               // after the newest comes now
  });

  it("from a moment between two events goes to the neighbours", () => {
    expect(jump(ms, at(6), -1)).toBe(at(8));
    expect(jump(ms, at(6), 1)).toBe(at(5));
  });

  it("with nothing to go to, stays where it is", () => {
    expect(jump([], null, -1)).toBeNull();
    expect(jump([], at(3), 1)).toBeNull();               // nothing after: now
    expect(jump([], at(3), -1)).toBe(at(3));
  });
});

describe("playPlan — P: the day's moments in order, ending at now", () => {
  it("is every moment when there are few, then now", () => {
    expect(playPlan([at(8), at(5), at(2)], 60)).toEqual([at(8), at(5), at(2), null]);
  });

  it("is a spread sample when there are many — the first and the last moment always in it", () => {
    const many = Array.from({ length: 300 }, (_x, i) => NOW - REPLAY_MS + i * 60_000);
    const plan = playPlan(many, 60);
    expect(plan).toHaveLength(61);                        // 60 moments and now
    expect(plan[0]).toBe(many[0]);
    expect(plan[59]).toBe(many[299]);
    expect(plan[60]).toBeNull();
    expect([...plan.slice(0, 60)].sort((a, b) => (a as number) - (b as number))).toEqual(plan.slice(0, 60));
  });

  it("is nothing when nothing happened", () => {
    expect(playPlan([], 60)).toEqual([]);
  });
});
