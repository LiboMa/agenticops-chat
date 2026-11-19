import { describe, it, expect } from "vitest";
import { contextRefFromPath, contextRefFromQuery, contextRefQuery, refLabel } from "@/lib/contextRef";

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

describe("contextRefFromQuery (Ask Agent, MVP-2.7.0 S4)", () => {
  it("?ref=I12 / C3 (or I#12) opens Chat with that record as its context", () => {
    expect(contextRefFromQuery("?ref=I12")).toEqual({ kind: "issue", id: 12 });
    expect(contextRefFromQuery("?ref=C3")).toEqual({ kind: "change", id: 3 });
    expect(contextRefFromQuery("?ref=I%2312")).toEqual({ kind: "issue", id: 12 });
  });
  it("anything else is no context", () => {
    for (const s of ["?ref=x", "?ref=I0", "?ref=I-1", "?ref=R12", "", "?other=I12"]) expect(contextRefFromQuery(s)).toBeNull();
  });
  it("the query round-trips", () => {
    expect(contextRefQuery({ kind: "issue", id: 12 })).toBe("?ref=I12");
    expect(contextRefFromQuery(contextRefQuery({ kind: "change", id: 3 }))).toEqual({ kind: "change", id: 3 });
  });
});

describe("startsFresh — /app/chat opens a NEW conversation instead of resuming the last one (MVP-2.9.0 N19)", () => {
  it("when it was opened about a record", async () => {
    const { startsFresh } = await import("@/lib/contextRef");
    expect(startsFresh("?ref=I12", null)).toBe(true);
    expect(startsFresh("?ref=C3", undefined)).toBe(true);
  });
  it("when the link says so (NewUI's command bar brings a sentence into the new conversation's draft)", async () => {
    const { startsFresh, FRESH_CHAT } = await import("@/lib/contextRef");
    expect(startsFresh("", FRESH_CHAT)).toBe(true);
    expect(startsFresh("", { fresh: true, other: 1 })).toBe(true);
  });
  it("otherwise the last conversation is resumed, as before", async () => {
    const { startsFresh } = await import("@/lib/contextRef");
    for (const state of [null, undefined, {}, { fresh: false }, { fresh: "yes" }, "fresh", 1]) expect(startsFresh("", state)).toBe(false);
    expect(startsFresh("?ref=nope", null)).toBe(false);
    expect(startsFresh("?q=x", null)).toBe(false);
  });
});
