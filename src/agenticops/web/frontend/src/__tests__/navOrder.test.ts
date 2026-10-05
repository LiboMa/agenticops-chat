import { describe, it, expect } from "vitest";
import { reorderNavIds, moveId } from "@/lib/navOrder";
import { NAV_ITEMS } from "@/components/layout/NavItems";

describe("NAV_ITEMS", () => {
  it("Resources has its own entry after Changes (spec §3); signals stay out of the sidebar", () => {
    expect(NAV_ITEMS.map((i) => i.id)).toEqual([
      "dashboard", "chat", "issues", "changes", "resources", "audit", "schedules", "reports", "agent-metrics", "skills",
      "galaxy", "security",
    ]);
  });
});

describe("reorderNavIds", () => {
  it("keeps stored order for known ids", () => {
    expect(reorderNavIds(["b", "a"], ["a", "b"])).toEqual(["b", "a"]);
  });
  it("drops ids no longer current", () => {
    expect(reorderNavIds(["x", "a"], ["a"])).toEqual(["a"]);
  });
  it("appends new current ids at the end", () => {
    expect(reorderNavIds(["b", "a"], ["a", "b", "c"])).toEqual(["b", "a", "c"]);
  });
  it("empty stored → current as-is", () => {
    expect(reorderNavIds([], ["a", "b"])).toEqual(["a", "b"]);
  });
  it("a renamed id takes its successors into the old slot", () => {
    expect(reorderNavIds(["b", "old", "a"], ["a", "new1", "b", "new2"], { old: ["new1", "new2"] }))
      .toEqual(["b", "new1", "new2", "a"]);
  });
  it("a successor already stored is not listed twice", () => {
    expect(reorderNavIds(["new1", "old"], ["new1", "new2"], { old: ["new1", "new2"] })).toEqual(["new1", "new2"]);
  });
});

describe("moveId", () => {
  it("moves source before target", () => {
    expect(moveId(["a", "b", "c"], "c", "a")).toEqual(["c", "a", "b"]);
  });
  it("no-op when source === target", () => {
    expect(moveId(["a", "b"], "a", "a")).toEqual(["a", "b"]);
  });
  it("unknown ids → unchanged", () => {
    expect(moveId(["a", "b"], "x", "a")).toEqual(["a", "b"]);
  });
});
