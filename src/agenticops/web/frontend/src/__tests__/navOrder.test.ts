import { describe, it, expect } from "vitest";
import { reorderNavIds, moveId } from "@/lib/navOrder";

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
