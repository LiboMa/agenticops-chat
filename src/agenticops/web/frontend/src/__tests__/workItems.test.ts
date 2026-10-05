import { describe, it, expect } from "vitest";
import type { Anomaly, ChangeRequest } from "@/api/types";
import { changeRow, issueRow } from "@/lib/workItems";

const anomaly = (x: Partial<Anomaly>) => ({ id: 1, title: "EKS-agenticops-chaos-lab-RunningPods-Low", status: "root_cause_identified",
  severity: "high", resource_id: "unknown", resource_type: "unknown", account_name: "chaos-lab", detected_at: "2026-10-03T03:39:04",
  ...x }) as Anomaly;

describe("issueRow (list mode, R2)", () => {
  it("I#1: locale status, the same wait key the page would say in list mode, no raw enum", () => {
    const r = issueRow(anomaly({}));
    expect(r).toMatchObject({ ref: "I#1", href: "/app/issues/1", statusKey: "issues.status.root_cause_identified",
                              waitKey: "workitem.wait.you", level: "high", account: "chaos-lab" });
    expect(r.subtitle).toBeNull(); // "unknown" is not a subtitle
    expect(r.dots.map((d) => d.state)).toEqual(["current", "future", "future", "future"]);
  });
  it("a resolved issue has no wait; a real resource id is the subtitle", () => {
    const r = issueRow(anomaly({ status: "resolved", resource_type: "EC2", resource_id: "i-0abc" }));
    expect(r.waitKey).toBeNull();
    expect(r.subtitle).toBe("EC2 · i-0abc");
  });
});

describe("changeRow", () => {
  it("C#1 failed: the dots end at the failed phase; next step copy-as-new is the wait text", () => {
    const r = changeRow({ id: 1, title: "E2E intake", status: "failed", review_verdict: "approved_for_planning",
      approved_at: "x", risk_level: "L1", requested_by: "webhook:e2e-itsm", external_ref: { system: "e2e-itsm", ticket_id: "CHG-1001" },
      updated_at: "2026-10-03T09:56:39", created_at: null } as unknown as ChangeRequest, "chaos-lab");
    expect(r).toMatchObject({ ref: "C#1", href: "/app/changes/1", statusKey: "changes.status.failed",
                              waitKey: "workitem.primary.copyAsNew", level: "L1", account: "chaos-lab" });
    expect(r.subtitle).toBe("webhook:e2e-itsm · e2e-itsm CHG-1001");
    expect(r.dots.map((d) => d.state)).toEqual(["done", "done", "done", "failed"]);
  });
});

describe("issueRow — row cues (fix round 1)", () => {
  it("an ARN keeps its meaningful tail, the full id stays for the tooltip; the region is shown when present", () => {
    const arn = "arn:aws:eks:us-east-1:123456789012:cluster/agenticops-chaos-lab";
    const r = issueRow(anomaly({ resource_type: "EKS", resource_id: arn, region: "us-east-1" }));
    expect(r.subtitle).toBe("EKS · agenticops-chaos-lab · us-east-1");
    expect(r.subtitleFull).toBe(`EKS · ${arn} · us-east-1`);
  });
  it("a long plain id keeps its last 28 characters; an 'unknown' region is not shown", () => {
    const r = issueRow(anomaly({ resource_type: "Pod", resource_id: "frontend-7d9f8b6c5-abcde-0123456789", region: "unknown" }));
    expect(r.subtitle).toBe("Pod · …d-7d9f8b6c5-abcde-0123456789");
  });
  it("recurrence is occurrence_count, 1 when absent", () => {
    expect(issueRow(anomaly({ occurrence_count: 40 })).recurrence).toBe(40);
    expect(issueRow(anomaly({})).recurrence).toBe(1);
  });
  it("emphasis: an open critical issue is 'critical'; resolved / dismissed are 'closed' (even if critical); else none", () => {
    expect(issueRow(anomaly({ severity: "critical" })).emphasis).toBe("critical");
    expect(issueRow(anomaly({ severity: "critical", status: "resolved" })).emphasis).toBe("closed");
    expect(issueRow(anomaly({ status: "dismissed" })).emphasis).toBe("closed");
    expect(issueRow(anomaly({})).emphasis).toBeNull();
  });
  it("the time is the detection time, even once resolved; an issue has no change type", () => {
    const r = issueRow(anomaly({ status: "resolved", resolved_at: "2026-10-04T01:00:00" }));
    expect(r.time).toBe("2026-10-03T03:39:04");
    expect(r.typeKey).toBeNull();
  });
  it("fix_approved in list mode waits for the executor, never 'you' (not queued)", () => {
    expect(issueRow(anomaly({ status: "fix_approved" })).waitKey).toBe("workitem.wait.executor");
  });
});

describe("changeRow — more cases (fix round 1)", () => {
  const cr = (x: Partial<ChangeRequest>) => ({ id: 2, title: "Scale ng-app", status: "planned", review_verdict: "approved_for_planning",
    approved_at: null, risk_level: null, requested_by: "user:alice", external_ref: null, requested_change_type: "normal",
    effective_change_type: null, updated_at: null, created_at: "2026-10-03T08:00:00", ...x }) as ChangeRequest;
  it("no external ticket: the subtitle is the requester alone; no update yet: the time is created_at", () => {
    const r = changeRow(cr({}));
    expect(r.subtitle).toBe("user:alice");
    expect(r.subtitleFull).toBe("user:alice");
    expect(r.time).toBe("2026-10-03T08:00:00");
    expect(r.account).toBeNull();
  });
  it("cancelled: copy-as-new is the next step, the row is closed; completed: no wait, closed", () => {
    expect(changeRow(cr({ status: "cancelled" }))).toMatchObject({ waitKey: "workitem.primary.copyAsNew", emphasis: "closed" });
    expect(changeRow(cr({ status: "completed" }))).toMatchObject({ waitKey: null, emphasis: "closed" });
    expect(changeRow(cr({ status: "planned" }))).toMatchObject({ waitKey: "workitem.wait.approver", emphasis: null });
  });
  it("the type shown with the risk is the effective type, else the requested one; recurrence is always 1", () => {
    expect(changeRow(cr({})).typeKey).toBe("plans.changeType.normal");
    expect(changeRow(cr({ effective_change_type: "emergency" })).typeKey).toBe("plans.changeType.emergency");
    expect(changeRow(cr({})).recurrence).toBe(1);
  });
});
