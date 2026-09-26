import { describe, it, expect } from "vitest";
import { changeStepState, CHANGE_STEP_KEYS, type ChangeStepInput, type StepTone } from "@/lib/changeStepper";
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
  ["needs_review", { status: "needs_review", approved_at: "2026-09-20T00:00:00Z", review_verdict: PLAN_OK }, 5, "warn"],
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
