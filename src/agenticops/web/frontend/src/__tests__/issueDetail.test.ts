import { describe, it, expect } from "vitest";
import type { FixExecution, HealthIssue } from "@/api/types";
import { anchorBadge, issueFacts, issueStatuses, parseIssueTab, resultRow, resultSummary } from "@/lib/issueDetail";

function issue(extra: Partial<HealthIssue> = {}): HealthIssue {
  return {
    id: 12, resource_id: "i-0abc", provider: "aws", severity: "high", source: "cloudwatch_alarm", title: "cpu",
    description: "d", alarm_name: null, metric_data: {}, related_changes: [], status: "fix_executed",
    detected_at: "2026-09-28T01:00:00", detected_by: "detect_agent", resolved_at: null, trace_id: "TRC-1",
    occurrence_count: 1, merged_alerts: [], account_id: 1, account_name: "dev", issue_type: "other",
    resource_ref: null, anchor_status: null, anchor_candidates: null, observed_at: null, ...extra,
  };
}

function execution(id: number, created_at: string, extra: Partial<FixExecution> = {}): FixExecution {
  return {
    id, fix_plan_id: 3, health_issue_id: 12, status: "succeeded", started_at: null, completed_at: null,
    executed_by: "executor_agent", pre_check_results: [], step_results: [], post_check_results: [],
    rollback_results: [], error_message: null, duration_ms: 0, verification_status: null,
    verification_reason: null, accepted_by: null, accepted_at: null, acceptance_note: null, created_at, ...extra,
  };
}

describe("parseIssueTab", () => {
  it("reads the tab from the URL; the old `issue` tab and anything unknown open Investigate", () => {
    expect(parseIssueTab("verification")).toBe("verification");
    expect(parseIssueTab("fixPlan")).toBe("fixPlan");
    expect(parseIssueTab("issue")).toBe("investigate");
    expect(parseIssueTab("bogus")).toBe("investigate");
    expect(parseIssueTab(null)).toBe("investigate");
  });
});

describe("issueFacts", () => {
  it("lifts the resource and metric facts out of metric_data, null where the issue has none", () => {
    expect(issueFacts(issue({ metric_data: { resource_type: "EC2", region: "us-east-1", metric_name: "CPU",
                                             expected_value: 70, actual_value: 97 } })))
      .toEqual({ resourceType: "EC2", region: "us-east-1", metricName: "CPU", expected: 70, actual: 97 });
    expect(issueFacts(issue())).toEqual({ resourceType: null, region: null, metricName: null, expected: null,
                                          actual: null });
  });
});

describe("issueStatuses", () => {
  it("reads the business status off the issue and the other two off its newest execution", () => {
    const older = execution(1, "2026-09-28T01:00:00", { status: "failed", verification_status: "failed" });
    const newer = execution(2, "2026-09-28T02:00:00", { verification_status: "pending_acceptance",
                                                        verification_reason: "no post-checks declared" });
    const s = issueStatuses(issue(), [older, newer]);
    expect(s).toMatchObject({ business: "fix_executed", execution: "succeeded", verification: "pending_acceptance" });
    expect(s.latest?.id).toBe(2);
    expect(s.pending?.id).toBe(2);
  });

  it("offers acceptance only for the newest run, and only while it is pending", () => {
    const pendingOld = execution(1, "2026-09-28T01:00:00", { verification_status: "pending_acceptance" });
    const passedNew = execution(2, "2026-09-28T02:00:00", { verification_status: "passed" });
    expect(issueStatuses(issue(), [pendingOld, passedNew]).pending).toBeNull();
  });

  it("no acceptance once the issue has moved off fix_executed", () => {
    // the accept endpoint 409s unless the issue is still at fix_executed, so the page must not offer it
    const pending = execution(1, "2026-09-28T01:00:00", { verification_status: "pending_acceptance" });
    for (const status of ["resolved", "root_cause_identified"] as const) {
      const s = issueStatuses(issue({ status }), [pending]);
      expect(s.verification).toBe("pending_acceptance");
      expect(s.pending).toBeNull();
    }
  });

  it("an issue never executed has no execution or verification status", () => {
    expect(issueStatuses(issue({ status: "open" }), undefined))
      .toEqual({ business: "open", execution: null, verification: null, latest: null, pending: null });
  });
});

describe("anchorBadge", () => {
  it("an anchored issue links to its resource", () => {
    expect(anchorBadge(issue({ anchor_status: "anchored", resource_ref: 7 })))
      .toEqual({ kind: "resource", ref: 7, label: "i-0abc" });
  });

  it("otherwise names why not, with the candidate count when ambiguous", () => {
    const candidates = [{ ref: 1, account_id: 1, reason: "short_id" }, { ref: 2, account_id: 1, reason: "short_id" }];
    expect(anchorBadge(issue({ anchor_status: "ambiguous", anchor_candidates: { rule: "short_id", candidates } })))
      .toEqual({ kind: "ambiguous", candidates: 2 });
    expect(anchorBadge(issue({ anchor_status: "account_level" }))).toEqual({ kind: "account_level", candidates: 0 });
    expect(anchorBadge(issue({ anchor_status: "unanchored" }))).toEqual({ kind: "unanchored", candidates: 0 });
  });

  it("an issue the resolver has not reached yet shows no badge", () => {
    expect(anchorBadge(issue())).toBeNull();
  });
});

describe("resultRow", () => {
  it("reads the outcome the way services/verification._outcome does", () => {
    expect(resultRow({ status: "OK" }).outcome).toBe("pass");
    expect(resultRow({ result: "warning" }).outcome).toBe("warning");
    expect(resultRow({ passed: true }).outcome).toBe("pass");
    expect(resultRow({ passed: false }).outcome).toBe("fail");
    expect(resultRow({ status: "error" }).outcome).toBe("fail");
    expect(resultRow({ command: "uptime" }).outcome).toBe("missing");
    // `status` present but null wins over `result`, as dict.get does
    expect(resultRow({ status: null, result: "pass" }).outcome).toBe("missing");
    expect(resultRow("succeeded").outcome).toBe("pass");
  });

  it("titles a result by what it checked and keeps its whole output", () => {
    const long = "x".repeat(500);
    expect(resultRow({ step_index: 1, command: "kubectl rollout status", status: "succeeded", output: long }))
      .toEqual({ outcome: "pass", title: "kubectl rollout status", output: long });
    expect(resultRow({ check: "error rate < 1%", status: "fail", detail: { rate: 3.2 } }))
      .toEqual({ outcome: "fail", title: "error rate < 1%", output: '{"rate":3.2}' });
    expect(resultRow({ status: "pass" })).toEqual({ outcome: "pass", title: "", output: "" });
  });
});

describe("resultSummary", () => {
  it("counts each outcome", () => {
    expect(resultSummary([{ status: "ok" }, { status: "fail" }, { status: "ok" }, {}]))
      .toEqual({ pass: 2, warning: 0, fail: 1, missing: 1 });
  });
});
