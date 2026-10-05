import { describe, it, expect } from "vitest";
import type { FixExecution, FixPlan, RCAResult } from "@/api/types";
import { issueDetailModel } from "@/lib/issueDetailModel";

const rcaI1 = { confidence: 0.57, evidence_verified: false, critic_verdict: "weak", human_verdict: null } as RCAResult;
const run = (x: Partial<FixExecution>) => ({ id: 4, fix_plan_id: 1, status: "succeeded", verification_status: null,
  verification_reason: null, acceptance_note: null, error_message: null, created_at: "2026-10-03T10:00:00", ...x }) as FixExecution;

describe("issueDetailModel", () => {
  it("I#1: one primary (review root cause), the pause explained with the gate's numbers, menu holds the rest", () => {
    const m = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [] });
    expect(m.primaryKey).toBe("workitem.primary.reviewRca");
    expect(m.statusKey).toBe("workitem.sub.needsReview");
    expect(m.reason).toEqual({ key: "workitem.reason.rcaBelowGate", params: { conf: "57%", threshold: "60%" } });
    expect(m.menu).toEqual(["runRca", "skipReviewGeneratePlan", "markResolved", "dismiss"]);
    expect(m.tone).toBe("warn");
  });
  it("a failed run: the failure sentence is the status line's reason — the run's own text, once", () => {
    const failed = run({ status: "failed", verification_status: "failed", verification_reason: "post-check 2 failed" });
    const m = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: { ...rcaI1, confidence: 0.9, evidence_verified: true } as RCAResult,
                                 threshold: 0.6, plans: [], executions: [failed] });
    expect(m.reason).toEqual({ text: "post-check 2 failed" });
    expect(m.tone).toBe("bad");
    expect(JSON.stringify(m).split("post-check 2 failed").length - 1).toBe(2); // the reason + the run row itself, nothing else
  });
  it("pending acceptance only for the newest run while the issue is at fix_executed", () => {
    const pend = run({ id: 5, verification_status: "pending_acceptance", verification_reason: "no post-checks declared" });
    const m = issueDetailModel({ issue: { status: "fix_executed" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [pend] });
    expect(m.pendingRun?.id).toBe(5);
    expect(m.primaryKey).toBe("workitem.primary.acceptResult");
    expect(m.reason).toEqual({ text: "no post-checks declared" });
    const moved = issueDetailModel({ issue: { status: "resolved" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [pend] });
    expect(moved.pendingRun).toBeNull();
  });
  it("no RCA at all (Review Focus 1): running, no primary, menu offers Run RCA", () => {
    const m = issueDetailModel({ issue: { status: "open" }, rca: null, threshold: 0.6, plans: undefined, executions: undefined });
    expect([m.primaryKey, m.reason]).toEqual([null, null]);
    expect(m.menu[0]).toBe("runRca");
  });
  it("approved but not queued → retry is the primary and the reason says so", () => {
    const plan = { id: 1, status: "approved", created_at: "2026-10-03T09:00:00" } as FixPlan;
    const m = issueDetailModel({ issue: { status: "fix_approved" }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: [] });
    expect(m.primaryKey).toBe("workitem.primary.retryExecution");
    expect(m.reason).toEqual({ key: "workitem.reason.notQueued" });
  });
  it("terminal: no primary; menu has reopen only", () => {
    const m = issueDetailModel({ issue: { status: "dismissed" }, rca: null, threshold: 0.6, plans: [], executions: [] });
    expect([m.primaryKey, m.menu]).toEqual([null, ["reopen"]]);
  });
});
