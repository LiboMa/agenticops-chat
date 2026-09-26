import type { ChangeRequest } from "@/api/types";

// Pure stepper state for a change request (M16). No React, no i18n — the label lookup lives in the component.
// The table mirrors CHANGE_TRANSITIONS in src/agenticops/models.py: cancel is allowed from
// draft/needs_clarification/planned/approved; reject from under_review (the review) or planned (a human).

export type ChangeStepInput = Pick<ChangeRequest, "status" | "approved_at" | "review_verdict">;
export type StepTone = "progress" | "warn" | "bad" | "done";
export interface ChangeStepState {
  index: number;
  tone: StepTone;
}

/** Steps: 0 Requested, 1 Reviewed, 2 Planned, 3 Approved, 4 Executed, 5 Completed. */
export const CHANGE_STEP_KEYS = [
  "changes.step.requested",
  "changes.step.reviewed",
  "changes.step.planned",
  "changes.step.approved",
  "changes.step.executed",
  "changes.step.completed",
] as const;

export function changeStepState(cr: ChangeStepInput): ChangeStepState {
  switch (cr.status) {
    case "draft":
      return { index: 0, tone: "progress" };
    case "under_review":
      return { index: 1, tone: "progress" };
    case "needs_clarification":
      return { index: 1, tone: "warn" };
    case "planned":
      return { index: 2, tone: "progress" };
    case "approved":
      return { index: 3, tone: "progress" };
    case "executing":
      return { index: 4, tone: "progress" };
    case "completed":
      return { index: 5, tone: "done" };
    case "needs_review":
      return { index: 5, tone: "warn" };
    case "failed":
    case "rolled_back":
      return { index: 4, tone: "bad" };
    case "rejected":
      // A human rejected the plan (review had passed it) -> step 3; else the review rejected it -> step 1.
      return { index: cr.review_verdict === "approved_for_planning" ? 3 : 1, tone: "bad" };
    case "cancelled":
      // Cancelled after approval -> step 4; after the review passed it -> step 3; before either -> step 1.
      return {
        index: cr.approved_at ? 4 : cr.review_verdict === "approved_for_planning" ? 3 : 1,
        tone: "bad",
      };
    default:
      return { index: 0, tone: "progress" };
  }
}
