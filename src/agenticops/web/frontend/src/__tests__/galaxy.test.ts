import { describe, it, expect } from "vitest";
import { buildLanded, focusNodeId, galaxyFocusPath } from "@/lib/galaxy";

describe("focusNodeId", () => {
  it("reads a resource ref in any of the spellings a link or a person uses", () => {
    for (const v of ["12", "R12", "r#12", "R#12", "res:12", " 12 "]) expect(focusNodeId(v)).toBe("res:12");
  });

  it("anything else is no focus", () => {
    for (const v of [null, "", "i-0abc", "acct:1", "res:", "I#12", "12a"]) expect(focusNodeId(v)).toBeNull();
  });

  it("round-trips the link LocalGraph builds", () => {
    const ref = new URL(galaxyFocusPath(7), "http://x").searchParams.get("focus");
    expect(focusNodeId(ref)).toBe("res:7");
  });
});

describe("buildLanded", () => {
  const running = { id: 5, status: "running" as const };
  const done = { id: 5, status: "completed" as const };

  it("the first observation never counts: what is loaded is already current", () => {
    expect(buildLanded(undefined, done)).toBe(false);
  });

  it("the running build finishing, a new completed build, or the first build ever all count", () => {
    expect(buildLanded(running, done)).toBe(true);
    expect(buildLanded(done, { id: 6, status: "completed" })).toBe(true);
    expect(buildLanded(null, done)).toBe(true);
  });

  it("the same completed build again, a build still running or one that failed does not", () => {
    expect(buildLanded(done, done)).toBe(false);
    expect(buildLanded(done, { id: 6, status: "running" })).toBe(false);
    expect(buildLanded(running, { id: 5, status: "failed" })).toBe(false);
    expect(buildLanded(done, null)).toBe(false);
  });
});
