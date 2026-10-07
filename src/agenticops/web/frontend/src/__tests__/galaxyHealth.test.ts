import { describe, it, expect } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { HEALTH_VALUES, healthCounts, isHot, normalizeHealth } from "@/lib/galaxyHealth";

// Mirrors graph/query_service.HEALTH_RANK. No open issue is `unknown`, not healthy (spec §3.A.6).
describe("normalizeHealth", () => {
  it("keeps the four server values", () => {
    for (const h of ["unknown", "notice", "warning", "critical"]) expect(normalizeHealth(h)).toBe(h);
  });
  it("missing, legacy and inherited-property values are unknown", () => {
    expect(normalizeHealth(undefined)).toBe("unknown");
    expect(normalizeHealth(null)).toBe("unknown");
    expect(normalizeHealth("healthy")).toBe("unknown");
    expect(normalizeHealth("toString")).toBe("unknown");
  });
});

describe("isHot", () => {
  it("only warning and critical pulse", () => {
    expect(HEALTH_VALUES.filter(isHot)).toEqual(["warning", "critical"]);
  });
});

describe("healthCounts", () => {
  it("tallies resource nodes over the four values", () => {
    const nodes = [
      { kind: "resource", health: "critical" },
      { kind: "resource", health: "notice" },
      { kind: "resource", health: "notice" },
      { kind: "resource" },
      { kind: "resource", health: "healthy" },
      { kind: "account", health: "critical" },
      { kind: "group" },
    ];
    expect(healthCounts(nodes)).toEqual({ unknown: 2, notice: 2, warning: 0, critical: 1 });
  });
});

describe("locales", () => {
  it("en and zh have the same keys", () => {
    expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort());
  });
  it("every health value has a label and no healthy label is left", () => {
    for (const h of HEALTH_VALUES) expect(en).toHaveProperty([`galaxy.health.${h}`]);
    expect(Object.keys(en).filter((k) => k.includes("ealthy"))).toEqual([]);
  });
});
