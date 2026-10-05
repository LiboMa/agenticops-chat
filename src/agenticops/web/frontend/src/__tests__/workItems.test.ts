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
