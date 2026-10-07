import { describe, it, expect } from "vitest";
import { countParts, runBlocker } from "@/lib/connectors";

describe("countParts", () => {
  it("lists the non-zero counts in reading order", () => {
    expect(countParts({ absent: 1, returned: 0, created: 2, signals: 3, updated: 5 }))
      .toEqual([["created", 2], ["updated", 5], ["absent", 1], ["signals", 3]]);
  });

  it("a key it does not know goes last instead of being dropped; nothing → nothing", () => {
    expect(countParts({ zeta: 1, created: 1, alpha: 2 })).toEqual([["created", 1], ["alpha", 2], ["zeta", 1]]);
    expect(countParts({})).toEqual([]);
    expect(countParts(null)).toEqual([]);
  });
});

describe("runBlocker", () => {
  it("mirrors the run endpoint's 409s: a disabled connector first, then one already running", () => {
    expect(runBlocker({ enabled: false, running: true })).toBe("disabled");
    expect(runBlocker({ enabled: true, running: true })).toBe("running");
    expect(runBlocker({ enabled: true, running: false })).toBeNull();
  });
});
