import { describe, expect, it } from "vitest";
import { accuracyView, costExact, costLabel, costPeriod, metricsQuery, metricsSearch, rangeLabel, tokenHours } from "@/lib/agentMetrics";

const q = (s: string) => metricsQuery(new URLSearchParams(s));

describe("the page's one range, in the address (MVP-2.9.0 N24 — the 2.8.0 spec's S7)", () => {
  it("30 days unless the address says 7 or 90; anything else is 30", () => {
    expect(q("")).toEqual({ days: 30, cost: null, tokens: null });
    expect(q("days=7").days).toBe(7);
    expect(q("days=90").days).toBe(90);
    expect(q("days=14").days).toBe(30);
    expect(q("days=abc").days).toBe(30);
  });
  it("a module may keep a range of its own — only the ones the page's range cannot say", () => {
    expect(q("cost=month&tokens=6h")).toEqual({ days: 30, cost: "month", tokens: "6h" });
    expect(q("cost=7d&tokens=7d")).toEqual({ days: 30, cost: null, tokens: null });
  });
  it("defaults leave the address; the rest of it stays", () => {
    expect(metricsSearch(new URLSearchParams("x=1"), { days: 90 }).toString()).toBe("x=1&days=90");
    expect(metricsSearch(new URLSearchParams("days=90&cost=year"), { days: 30 }).toString()).toBe("cost=year");
    expect(metricsSearch(new URLSearchParams("cost=year"), { cost: null }).toString()).toBe("");
    expect(metricsSearch(new URLSearchParams("days=7"), { tokens: "24h" }).toString()).toBe("days=7&tokens=24h");
  });
});

describe("what each module asks the server for", () => {
  it("cost follows the page, or its own month / year view", () => {
    expect(costPeriod(q("days=7"))).toBe("7d");
    expect(costPeriod(q(""))).toBe("30d");
    expect(costPeriod(q("days=90"))).toBe("90d");
    expect(costPeriod(q("days=90&cost=year"))).toBe("year");
  });
  it("tokens follow the page in hours, or their own 1 / 6 / 24 hours", () => {
    expect(tokenHours(q("days=7"))).toBe(168);
    expect(tokenHours(q("days=90"))).toBe(2160);
    expect(tokenHours(q("days=90&tokens=6h"))).toBe(6);
    expect(tokenHours(q("tokens=24h"))).toBe(24);
  });
});

describe("every module says its range", () => {
  it("the page's range, in days", () => {
    expect(rangeLabel(q("days=7"), "cost")).toEqual({ key: "metrics.range.days", n: 7, own: false });
    expect(rangeLabel(q("days=90"), "location")).toEqual({ key: "metrics.range.days", n: 90, own: false });
    expect(rangeLabel(q(""), "tokens")).toEqual({ key: "metrics.range.days", n: 30, own: false });
  });
  it("a module on its own range says so", () => {
    expect(rangeLabel(q("cost=month"), "cost")).toEqual({ key: "metrics.range.month", n: 12, own: true });
    expect(rangeLabel(q("cost=year"), "cost")).toEqual({ key: "metrics.range.year", n: 3, own: true });
    expect(rangeLabel(q("tokens=6h"), "tokens")).toEqual({ key: "metrics.range.hours", n: 6, own: true });
    expect(rangeLabel(q("cost=month&tokens=6h"), "location")).toEqual({ key: "metrics.range.days", n: 30, own: false });  // another module's choice is not its own
  });
});

describe("a rate is never shown without what it was counted from", () => {
  it("2 of 2 judged, out of 15 RCAs — a small sample", () => {
    expect(accuracyView({ correct: 2, judged: 2, rcas: 15 })).toEqual({ correct: 2, judged: 2, rcas: 15, small: true, none: false });
  });
  it("twenty judged is no longer a small sample", () => {
    expect(accuracyView({ correct: 15, judged: 20, rcas: 40 })?.small).toBe(false);
    expect(accuracyView({ correct: 15, judged: 19, rcas: 40 })?.small).toBe(true);
  });
  it("nothing judged is said as that, not as 0 %", () => {
    expect(accuracyView({ correct: 0, judged: 0, rcas: 7 })).toEqual({ correct: 0, judged: 0, rcas: 7, small: false, none: true });
  });
  it("an older server (no counts) is nothing to state", () => {
    expect(accuracyView({ judged: 3 } as never)).toBeNull();
    expect(accuracyView(undefined)).toBeNull();
  });
});

describe("a cost at a readable precision", () => {
  it("three figures or so — never four decimals of noise", () => {
    expect(costLabel(12.3456)).toBe("$12.3");
    expect(costLabel(1.2345)).toBe("$1.23");
    expect(costLabel(0.1234)).toBe("$0.12");
    expect(costLabel(123.456)).toBe("$123");
    expect(costLabel(1234.56)).toBe("$1,235");
    expect(costLabel(99.96)).toBe("$100");
    expect(costLabel(9.996)).toBe("$10.0");
  });
  it("nothing is $0; less than a cent is said as that", () => {
    expect(costLabel(0)).toBe("$0");
    expect(costLabel(0.004)).toBe("<$0.01");
    expect(costLabel(0.01)).toBe("$0.01");
  });
  it("a figure that is not a cost is a dash", () => {
    expect(costLabel(Number.NaN)).toBe("—");
    expect(costLabel(-1)).toBe("—");
    expect(costLabel(undefined as never)).toBe("—");
  });
  it("the exact figure, for the tooltip", () => {
    expect(costExact(12.3456)).toBe("$12.3456");
    expect(costExact(0.000123)).toBe("$0.000123");
    expect(costExact(5)).toBe("$5");
    expect(costExact(Number.NaN)).toBe("—");
  });
});
