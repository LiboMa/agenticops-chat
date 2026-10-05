import { describe, it, expect } from "vitest";
import { choiceAvailable, locationJudgeable, noteRequired, verdictRequests } from "@/lib/verdict";

const valid = { location_status: "valid" as const, location_verdict: null };
const absent = { location_status: "absent" as const, location_verdict: null };

describe("verdict (P9): one block, the existing two endpoints", () => {
  it("both right → RCA correct + location correct, then confirmed", () => {
    expect(verdictRequests("correct", valid, "")).toEqual({
      rcaFeedback: { verdict: "correct", location_verdict: "correct" },
      issueFeedback: { type: "confirmed", confidence: 5 },
    });
  });
  it("no judgeable location → the location verdict is left out (the backend would 409)", () => {
    expect(verdictRequests("correct", absent, "").rcaFeedback).toEqual({ verdict: "correct" });
    expect(verdictRequests("correct", { location_status: "valid", location_verdict: "partial" }, "").rcaFeedback)
      .toEqual({ verdict: "correct" }); // already judged once
  });
  it("partly right needs a judgeable location", () => {
    expect(choiceAvailable("partial", valid)).toBe(true);
    expect(choiceAvailable("partial", absent)).toBe(false);
    expect(choiceAvailable("partial", null)).toBe(false);
    expect(verdictRequests("partial", valid, "").rcaFeedback).toEqual({ verdict: "correct", location_verdict: "partial" });
  });
  it("root cause wrong → RCA incorrect (+ location incorrect when judgeable) with the note; no issue feedback", () => {
    expect(verdictRequests("rcaWrong", valid, "it was the HPA")).toEqual({
      rcaFeedback: { verdict: "incorrect", location_verdict: "incorrect", note: "it was the HPA" }, issueFeedback: null,
    });
  });
  it("not an issue → false_positive with the note only (the backend dismisses the issue)", () => {
    expect(verdictRequests("falsePositive", null, " planned chaos ")).toEqual({
      rcaFeedback: null, issueFeedback: { type: "false_positive", note: "planned chaos", confidence: 4 },
    });
  });
  it("notes are required for the two negative choices; the RCA choices need an RCA", () => {
    expect(["correct", "partial", "rcaWrong", "falsePositive"].map((c) => noteRequired(c as never))).toEqual([false, false, true, true]);
    expect(choiceAvailable("correct", null)).toBe(false);
    expect(choiceAvailable("rcaWrong", null)).toBe(false);
    expect(choiceAvailable("falsePositive", null)).toBe(true);
    expect(locationJudgeable({ location_status: "partial", location_verdict: null })).toBe(true);
  });
});
