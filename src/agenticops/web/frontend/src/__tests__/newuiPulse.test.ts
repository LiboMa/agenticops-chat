import { describe, expect, it } from "vitest";
import { MAX_TICKS, bandTally, bandTicks, pulseX, type RecentEvent } from "@/newui/lib/pulse";

const NOW = Date.parse("2026-11-18T12:00:00Z");
const ev = (id: number, hoursAgo: number, kind: RecentEvent["kind"] = "agent", over: Partial<RecentEvent> = {}): RecentEvent => ({
  id, at: new Date(NOW - hoursAgo * 3_600_000).toISOString(), kind, type: "rca_completed", status: "completed", item: "I12", actor: "agent:rca",
  detail: {}, ...over,
});

describe("pulseX — where an hour sits on the band (recent hours get more room)", () => {
  it("now is the right edge, 24 hours ago the left, and nothing leaves the band", () => {
    expect(pulseX(0)).toBe(100);
    expect(pulseX(24)).toBe(0);
    expect(pulseX(30)).toBe(0);
    expect(pulseX(-1)).toBe(100);
  });

  it("the last hour takes a fifth of the band, the last six half of it", () => {
    expect(100 - pulseX(1)).toBeCloseTo(20.4, 1);
    expect(100 - pulseX(6)).toBeCloseTo(50, 5);
  });
});

describe("bandTicks — the events as marks, each where its time is", () => {
  it("keeps the order and gives each its place and its time", () => {
    const ticks = bandTicks([ev(1, 6, "signal"), ev(2, 1, "decision")], NOW);
    expect(ticks.map((t) => [t.id, t.kind, Math.round(t.left)])).toEqual([[1, "signal", 50], [2, "decision", 80]]);
  });

  it("drops what is outside the day or has no time, and never draws more than the cap — the newest stay", () => {
    expect(bandTicks([ev(1, 25), ev(2, -0.5), ev(3, 2, "agent", { at: "nonsense" }), ev(4, 2)], NOW).map((t) => t.id)).toEqual([4]);
    const many = Array.from({ length: MAX_TICKS + 10 }, (_x, i) => ev(i + 1, 23 - (i * 22) / (MAX_TICKS + 10)));
    const ticks = bandTicks(many, NOW);
    expect(ticks).toHaveLength(MAX_TICKS);
    expect(ticks[0].id).toBe(11);                       // the ten oldest are the ones left out
  });

  it("is empty for no answer", () => {
    expect(bandTicks(undefined, NOW)).toEqual([]);
  });
});

describe("bandTally — the band in numbers, for those who cannot hover", () => {
  it("counts each kind", () => {
    expect(bandTally([ev(1, 1, "signal"), ev(2, 2, "agent"), ev(3, 3, "agent"), ev(4, 4, "decision"), ev(5, 5, "change")]))
      .toEqual({ signal: 1, agent: 2, decision: 1, change: 1 });
    expect(bandTally(undefined)).toEqual({ signal: 0, agent: 0, decision: 0, change: 0 });
  });
});
