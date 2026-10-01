import { describe, it, expect } from "vitest";
import { contextRefFromPath, refLabel } from "@/lib/contextRef";

describe("contextRefFromPath", () => {
  it("an issue or a change route opens the context panel", () => {
    expect(contextRefFromPath("/app/issues/12")).toEqual({ kind: "issue", id: 12 });
    expect(contextRefFromPath("/app/changes/3")).toEqual({ kind: "change", id: 3 });
  });

  it("any other route navigates instead", () => {
    expect(contextRefFromPath("/app/resources/7")).toBeNull();
    expect(contextRefFromPath("/app/changes")).toBeNull();
    expect(contextRefFromPath("/app/changes/3/timeline")).toBeNull();
    expect(contextRefFromPath("/app/changes/0")).toBeNull();
    expect(contextRefFromPath("/app/issues/007")).toBeNull();
  });
});

describe("refLabel", () => {
  it("names the subject the way chat refs are written", () => {
    expect(refLabel({ kind: "issue", id: 12 })).toBe("I#12");
    expect(refLabel({ kind: "change", id: 3 })).toBe("C#3");
  });
});
