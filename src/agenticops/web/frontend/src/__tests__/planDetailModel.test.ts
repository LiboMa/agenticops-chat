import { describe, it, expect } from "vitest";
import { planDetailModel } from "@/lib/planDetailModel";
import { approvalCopy, canConfirm, findAction } from "@/lib/approval";
import type { FixExecution, FixPlan } from "@/api/types";

const plan = (over: Partial<FixPlan> = {}) => ({ id: 9, plan_kind: "fix", change_request_id: null, status: "pending_approval",
  available_actions: [{ action: "approve", allowed: true, reason_code: null, effect: "approve_only" },
                      { action: "reject", allowed: false, reason_code: "forbidden", effect: "update" }],
  target: { resource_id: "i-1", resource_ref: 44, anchor_status: "anchored", resource_type: "EC2", region: "us-east-1" },
  ...over }) as unknown as FixPlan;

describe("planDetailModel", () => {
  it("a change plan is shown on its change", () => {
    expect(planDetailModel(plan({ plan_kind: "change", change_request_id: 3 }), []).redirect).toBe("/app/changes/3");
    expect(planDetailModel(plan(), []).redirect).toBeNull();
  });
  it("offers only the actions the server allows (shadow-allowed counts)", () => {
    const m = planDetailModel(plan(), []);
    expect(m.actions.approve?.effect).toBe("approve_only");
    expect(m.actions.reject).toBeNull();
    expect(m.actions.execute).toBeNull();
    const shadow = planDetailModel(plan({ available_actions: [{ action: "approve", allowed: true, reason_code: "policy_shadow", effect: "approve_only" }] }), []);
    expect(shadow.actions.approve).not.toBeNull();
  });
  it("names the run state and links an anchored target only", () => {
    expect(planDetailModel(plan(), []).runKey).toBe("plans.run.notRun");
    expect(planDetailModel(plan({ status: "executing" }), []).runKey).toBe("plans.run.running");
    const runs = [{ id: 2, status: "failed", created_at: "2026-10-06T10:00:00Z" }] as unknown as FixExecution[];
    expect(planDetailModel(plan({ status: "executed" }), runs).runKey).toBe("plans.run.failed");
    expect(planDetailModel(plan(), []).targetLink).toBe("/app/resources/44");
    expect(planDetailModel(plan({ target: { resource_id: "i-1", resource_ref: 44, anchor_status: "ambiguous", resource_type: null, region: null } }), []).targetLink).toBeNull();
  });
});

describe("planDetailModel — final review I3 / U7", () => {
  it("names the account the plan runs in (the approval binds it: account is in the content hash)", () => {
    expect(planDetailModel(plan({ account_id: 4 }), []).accountId).toBe(4);
    expect(planDetailModel(plan({ account_id: null }), []).accountId).toBeNull();
  });
  it("polls while a run can move: approved, executing, or a run in flight; quiet otherwise", () => {
    expect(planDetailModel(plan({ status: "approved" }), []).pollMs).toBe(5000);
    expect(planDetailModel(plan({ status: "executing" }), []).pollMs).toBe(5000);
    const running = [{ id: 2, status: "running", created_at: "2026-10-06T10:00:00Z" }] as unknown as FixExecution[];
    expect(planDetailModel(plan({ status: "executed" }), running).pollMs).toBe(5000);
    expect(planDetailModel(plan({ status: "pending_approval" }), []).pollMs).toBe(false);
    const done = [{ id: 2, status: "succeeded", created_at: "2026-10-06T10:00:00Z" }] as unknown as FixExecution[];
    expect(planDetailModel(plan({ status: "executed" }), done).pollMs).toBe(false);
  });
});

describe("approval copy — what approving really does (MVP-2.7.0 S3)", () => {
  it("says run only when the server will queue the run", () => {
    expect(approvalCopy("approve_and_queue_execution")).toEqual({ titleKey: "approval.title.run", buttonKey: "approval.button.run", noteKey: "approval.note.run" });
    expect(approvalCopy("approve_only")).toEqual({ titleKey: "approval.title.only", buttonKey: "approval.button.only", noteKey: "approval.note.only" });
    expect(approvalCopy(undefined).buttonKey).toBe("approval.button.only");
    expect(approvalCopy(undefined).noteKey).toBe("approval.note.unknown");
  });
  it("confirm needs the acknowledgement when asked for, and a reason when required", () => {
    expect(canConfirm({ busy: false, required: false, reason: "", ack: true, acked: false })).toBe(false);
    expect(canConfirm({ busy: false, required: false, reason: "", ack: true, acked: true })).toBe(true);
    expect(canConfirm({ busy: false, required: true, reason: " ", ack: false, acked: false })).toBe(false);
    expect(canConfirm({ busy: true, required: false, reason: "x", ack: false, acked: false })).toBe(false);
  });
  it("a policy_shadow approve still reads by its effect", () => {
    expect(approvalCopy(findAction([{ action: "approve", allowed: true, reason_code: "policy_shadow", effect: "approve_and_queue_execution" }], "approve")?.effect).buttonKey).toBe("approval.button.run");
  });
  it("finds an action by name", () => {
    expect(findAction([{ action: "execute", allowed: true, reason_code: null, effect: "queue_execution" }], "execute")?.allowed).toBe(true);
    expect(findAction(undefined, "approve")).toBeNull();
  });
});
