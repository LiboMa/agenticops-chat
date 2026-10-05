import { describe, it, expect } from "vitest";
import {
  changeStepState, CHANGE_STEP_KEYS, stepLabelKey, visibleStepCount, type ChangeStepInput, type StepTone,
} from "@/lib/changeStepper";
import type { ChangeStatus } from "@/api/types";

// One row per line of R6's table: status -> { index, tone }. review_verdict "approved_for_planning" means the
// review passed the plan to a human; that human then approves (approved_at) or rejects it.
const PLAN_OK = "approved_for_planning";
type Row = [label: string, input: ChangeStepInput, index: number, tone: StepTone];

const rows: Row[] = [
  ["draft", { status: "draft", approved_at: null, review_verdict: null }, 0, "progress"],
  ["under_review", { status: "under_review", approved_at: null, review_verdict: null }, 1, "progress"],
  ["needs_clarification", { status: "needs_clarification", approved_at: null, review_verdict: null }, 1, "warn"],
  ["planned", { status: "planned", approved_at: null, review_verdict: PLAN_OK }, 2, "progress"],
  ["approved", { status: "approved", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 3, "progress"],
  ["executing", { status: "executing", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 4, "progress"],
  ["completed", { status: "completed", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 5, "done"],
  // executed, not yet accepted: the Executed step waits (amber); Completed is not reached
  ["needs_review", { status: "needs_review", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 4, "warn"],
  ["failed", { status: "failed", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 4, "bad"],
  ["rolled_back", { status: "rolled_back", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 4, "bad"],
  // rejected, branch 1: a human rejected the plan (review had approved it for planning)
  ["rejected after review passed", { status: "rejected", approved_at: null, review_verdict: PLAN_OK }, 3, "bad"],
  // rejected, branch 2: the review itself rejected it
  ["rejected at review", { status: "rejected", approved_at: null, review_verdict: null }, 1, "bad"],
  // cancelled, branch 1: approved (approved_at set) then cancelled
  ["cancelled after approval", { status: "cancelled", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 4, "bad"],
  // cancelled, branch 2: review passed it to a human, cancelled before approval
  ["cancelled after review passed", { status: "cancelled", approved_at: null, review_verdict: PLAN_OK }, 3, "bad"],
  // cancelled, branch 3: cancelled before the review passed it on
  ["cancelled before review", { status: "cancelled", approved_at: null, review_verdict: null }, 1, "bad"],
  // anything else -> step 0
  ["unknown status", { status: "not-a-real-status" as ChangeStatus, approved_at: null, review_verdict: null }, 0, "progress"],
];

describe("changeStepState (M16)", () => {
  it.each(rows)("%s -> { index, tone }", (_label, input, index, tone) => {
    expect(changeStepState(input)).toEqual({ index, tone });
  });

  it("CHANGE_STEP_KEYS is the six ordered step-label keys", () => {
    expect(CHANGE_STEP_KEYS).toEqual([
      "changes.step.requested", "changes.step.reviewed", "changes.step.planned",
      "changes.step.approved", "changes.step.executed", "changes.step.completed",
    ]);
  });
});

describe("stepLabelKey", () => {
  it("the current step reads the change's status — under review is not yet Reviewed", () => {
    const cr: ChangeStepInput = { status: "under_review", approved_at: null, review_verdict: null };
    expect(stepLabelKey(cr, 1)).toBe("changes.status.under_review");
    expect(stepLabelKey(cr, 0)).toBe("changes.step.requested");
    expect(stepLabelKey(cr, 2)).toBe("changes.step.planned");
  });

  it("an executing change reads Executing on the Executed step; a completed one reads Completed", () => {
    expect(stepLabelKey({ status: "executing", approved_at: "x", review_verdict: PLAN_OK }, 4))
      .toBe("changes.status.executing");
    expect(stepLabelKey({ status: "completed", approved_at: "x", review_verdict: PLAN_OK }, 5))
      .toBe("changes.status.completed");
    expect(stepLabelKey({ status: "needs_review", approved_at: "x", review_verdict: PLAN_OK }, 4))
      .toBe("changes.status.needs_review");
  });
});

describe("visibleStepCount (P12)", () => {
  const cr = (status: string, extra: Record<string, unknown> = {}) =>
    ({ status, approved_at: null, review_verdict: null, ...extra }) as Parameters<typeof visibleStepCount>[0];
  it("a bad ending is the last step drawn; a good or open path draws all steps", () => {
    expect(visibleStepCount(cr("failed"))).toBe(5);                       // ends at Executed
    expect(visibleStepCount(cr("rolled_back"))).toBe(5);
    expect(visibleStepCount(cr("rejected"))).toBe(2);                     // the review rejected it
    expect(visibleStepCount(cr("rejected", { review_verdict: "approved_for_planning" }))).toBe(4);
    expect(visibleStepCount(cr("cancelled", { approved_at: "2026-10-03T09:00:00" }))).toBe(5);
    expect(visibleStepCount(cr("completed"))).toBe(CHANGE_STEP_KEYS.length);
    expect(visibleStepCount(cr("planned"))).toBe(CHANGE_STEP_KEYS.length);
    expect(visibleStepCount(cr("needs_review"))).toBe(CHANGE_STEP_KEYS.length);
  });
});
