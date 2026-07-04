import { describe, it, expect } from "vitest";
import { agentShare } from "@/lib/agentShare";

describe("agentShare", () => {
  it("empty input → empty array", () => {
    expect(agentShare({})).toEqual([]);
  });
  it("single agent → 100%", () => {
    expect(agentShare({ main: { calls: 5 } })).toEqual([{ name: "main", calls: 5, pct: 100 }]);
  });
  it("multi agents sorted desc, pcts sum ~100", () => {
    const out = agentShare({ main: { calls: 6 }, scan: { calls: 3 }, sre: { calls: 1 } });
    expect(out.map((o) => o.name)).toEqual(["main", "scan", "sre"]);
    expect(out[0].pct).toBe(60);
    expect(out.reduce((s, o) => s + o.pct, 0)).toBeCloseTo(100, 0);
  });
  it("zero total calls → empty array", () => {
    expect(agentShare({ main: { calls: 0 } })).toEqual([]);
  });
});
