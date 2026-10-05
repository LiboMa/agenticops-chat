import { describe, it, expect } from "vitest";
import type { FixExecution, HealthIssue, PipelineEvent } from "@/api/types";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import {
  anchorBadge, approvalBlockedReason, canApprovePlan, executionStatusLabel, factRows, hasRunInFlight, inFlightAutoRun, isBlank, issueFacts,
  issueSourceLabel, ISSUE_SOURCES, issueStatuses, ISSUE_IN_FLIGHT, newestFirst, resultRow, resultSummary, SEVERITIES, severityLabel,
} from "@/lib/issueDetail";

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

describe("newestFirst", () => {
  it("orders runs by created_at, then id, whatever order they came in", () => {
    const runs = [execution(1, "2026-09-28T01:00:00"), execution(3, "2026-09-28T02:00:00"), execution(2, "2026-09-28T02:00:00")];
    expect(newestFirst(runs).map((e) => e.id)).toEqual([3, 2, 1]);
    expect(newestFirst(undefined)).toEqual([]);
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
    // a list is not a dict there (isinstance(item, dict)): it takes the non-object path and fails, not "missing"
    expect(resultRow(["x"]).outcome).toBe("fail");
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

describe("canApprovePlan", () => {
  it("approves a draft or pending plan of an open issue", () => {
    expect(canApprovePlan({ status: "draft" }, "fix_planned")).toBe(true);
    expect(canApprovePlan({ status: "pending_approval" }, "fix_planned")).toBe(true);
  });
  it("not once the issue is resolved or dismissed: the approve endpoint 409s", () => {
    for (const status of ["draft", "pending_approval"] as const) {
      expect(canApprovePlan({ status }, "resolved")).toBe(false);
      expect(canApprovePlan({ status }, "dismissed")).toBe(false);
    }
  });
  it("never a plan past approval, whatever its issue's status", () => {
    for (const status of ["approved", "executed"] as const) {
      for (const issueStatus of ["fix_planned", "fix_approved", "resolved", "dismissed", undefined]) {
        expect(canApprovePlan({ status }, issueStatus)).toBe(false);
      }
    }
  });
  it("a pending plan with no issue status to check is approvable", () => {
    expect(canApprovePlan({ status: "pending_approval" }, undefined)).toBe(true);
  });
});

describe("approvalBlockedReason", () => {
  it("names the closed issue status that blocks an approvable plan", () => {
    expect(approvalBlockedReason({ status: "pending_approval" }, "resolved")).toBe("resolved");
    expect(approvalBlockedReason({ status: "draft" }, "dismissed")).toBe("dismissed");
  });
  it("null for an open issue, or a plan that is not approvable anyway", () => {
    expect(approvalBlockedReason({ status: "pending_approval" }, "fix_planned")).toBeNull();
    expect(approvalBlockedReason({ status: "approved" }, "resolved")).toBeNull();
  });
});

describe("ISSUE_IN_FLIGHT", () => {
  it("holds the statuses between approval and the run's verdict", () => {
    expect([...ISSUE_IN_FLIGHT].sort()).toEqual(["fix_approved", "fix_executing"]);
    expect(ISSUE_IN_FLIGHT.has("fix_executed")).toBe(false);
    expect(ISSUE_IN_FLIGHT.has("fix_planned")).toBe(false);
  });
});

describe("hasRunInFlight", () => {
  it("true while a run is queued or claimed, false once every run has finished", () => {
    expect(hasRunInFlight([execution(1, "2026-09-28T01:00:00", { status: "pending" })])).toBe(true);
    expect(hasRunInFlight([execution(1, "2026-09-28T01:00:00", { status: "failed" }),
                           execution(2, "2026-09-28T02:00:00", { status: "running" })])).toBe(true);
    expect(hasRunInFlight([execution(1, "2026-09-28T01:00:00"), execution(2, "2026-09-28T02:00:00", { status: "rolled_back" })]))
      .toBe(false);
    expect(hasRunInFlight([])).toBe(false);
    expect(hasRunInFlight(undefined)).toBe(false);
  });
});

describe("anchorBadge with the resource name (P8)", () => {
  it("names the anchored resource, not the alarm's raw resource_id; falls back to #ref, never to 'unknown'", () => {
    const i = issue({ resource_id: "unknown", resource_ref: 36, anchor_status: "anchored" });
    expect(anchorBadge(i, "agenticops-chaos-lab")).toEqual({ kind: "resource", ref: 36, label: "agenticops-chaos-lab" });
    expect(anchorBadge(i)).toEqual({ kind: "resource", ref: 36, label: "#36" });
    expect(anchorBadge(issue({ resource_id: "i-0abc", resource_ref: 5, anchor_status: "anchored" }))).toEqual(
      { kind: "resource", ref: 5, label: "i-0abc" });
  });
});

describe("factRows", () => {
  const t = (k: string) => `<${k}>`;
  it("drops empty, 'unknown' and dash values; the anchor row links the resource with its name and type", () => {
    const i = issue({ resource_id: "unknown", resource_ref: 36, anchor_status: "anchored", account_name: "chaos-lab",
                      source: "cloudwatch_alarm", metric_data: { resource_type: "unknown", region: "—" } });
    const rows = factRows(i, { name: "agenticops-chaos-lab", type: "EKS" }, t);
    expect(rows.map((r) => r.labelKey)).toEqual(
      ["facts.anchor", "facts.account", "facts.severity", "facts.source", "facts.detected", "facts.trace"]);
    expect(rows[0]).toEqual({ labelKey: "facts.anchor", value: "agenticops-chaos-lab · EKS", href: "/app/resources/36" });
    expect(rows.find((r) => r.labelKey === "facts.detected")?.kind).toBe("date");
    // the trace id is copied with a click, as the old header's chip was
    expect(rows.find((r) => r.labelKey === "facts.trace")).toEqual({ labelKey: "facts.trace", value: "TRC-1", kind: "mono", copy: true });
    // severity and source in the reader's language (spec §1-6), not "HIGH" / cloudwatch_alarm
    expect(rows.find((r) => r.labelKey === "facts.severity")?.value).toBe("<severity.high>");
    expect(rows.find((r) => r.labelKey === "facts.source")?.value).toBe("<issues.source.cloudwatch_alarm>");
  });
  it("the root-cause resource: the top validated location candidate, linked, after the anchor facts (spec §6.1)", () => {
    const loc = (location_status: "valid" | "partial" | "invalid" | "absent", candidates: object[]) =>
      ({ location_status, location: { candidates, path: [], dropped: [] } }) as never;
    const cands = [{ ref: 7, rank: 2, type: "EC2", name: "web", resource_id: "i-1", supporting: [], refuting: [] },
                   { ref: 9, rank: 1, type: "RDS", name: "db-1", resource_id: "db-1", supporting: [], refuting: [] }];
    const i = issue({ metric_data: { region: "us-east-1" } });
    const rows = factRows(i, null, t, loc("valid", cands));
    expect(rows.map((r) => r.labelKey).slice(0, 4)).toEqual(["facts.resource", "facts.region", "facts.rootCause", "facts.account"]);
    expect(rows[2]).toEqual({ labelKey: "facts.rootCause", value: "db-1 · RDS", href: "/app/resources/9" });
    expect(factRows(i, null, t, loc("partial", [{ ...cands[1], name: null, type: null }]))
      .find((r) => r.labelKey === "facts.rootCause")?.value).toBe("db-1");
    expect(factRows(i, null, t, loc("partial", [{ ...cands[1], name: null, resource_id: null, type: null }]))
      .find((r) => r.labelKey === "facts.rootCause")?.value).toBe("#9");
    // a location that failed validation (or none) names no root cause
    for (const l of [loc("invalid", cands), loc("absent", []), null, undefined])
      expect(factRows(i, null, t, l).some((r) => r.labelKey === "facts.rootCause")).toBe(false);
  });
  it("an unanchored issue with a real resource id shows it as the resource row; region/type when present", () => {
    const rows = factRows(issue({ resource_id: "i-0abc", metric_data: { resource_type: "EC2", region: "us-east-1" } }), null, t);
    expect(rows.slice(0, 3)).toEqual([
      { labelKey: "facts.resource", value: "i-0abc", kind: "mono" },
      { labelKey: "facts.type", value: "EC2" },
      { labelKey: "facts.region", value: "us-east-1" },
    ]);
  });
  it("isBlank", () => {
    for (const v of ["", " ", "unknown", "Unknown", "—", "-", "n/a", null, undefined]) expect(isBlank(v), String(v)).toBe(true);
    for (const v of ["x", 0, "0"]) expect(isBlank(v), String(v)).toBe(false);
  });
});

describe("issueSourceLabel", () => {
  it("a source the backend writes reads as its key; webhook_ / im_ name their system; anything else stays raw", () => {
    const t = (k: string) => (k === "issues.source.webhook" ? "Webhook · {name}" : k === "issues.source.im" ? "IM · {name}" : `<${k}>`);
    expect(issueSourceLabel("cloudwatch_alarm", t)).toBe("<issues.source.cloudwatch_alarm>");
    expect(issueSourceLabel("webhook_datadog", t)).toBe("Webhook · datadog");
    expect(issueSourceLabel("im_prometheus", t)).toBe("IM · prometheus");
    expect(issueSourceLabel("agent", t)).toBe("agent");
    expect(issueSourceLabel("webhook_", t)).toBe("webhook_");
  });
  it("every known source (and the two families) has a label in both locales", () => {
    for (const k of [...ISSUE_SOURCES, "webhook", "im"]) {
      expect((en as Record<string, string>)[`issues.source.${k}`], k).toBeTruthy();
      expect((zh as Record<string, string>)[`issues.source.${k}`], k).toBeTruthy();
    }
  });
});

describe("severityLabel", () => {
  it("a severity the backend writes reads as its locale key; an unknown one stays as the raw value", () => {
    const t = (k: string) => `<${k}>`;
    expect(["critical", "high", "medium", "low"].map((s) => severityLabel(s, t)))
      .toEqual(["<severity.critical>", "<severity.high>", "<severity.medium>", "<severity.low>"]);
    expect(severityLabel("info", t)).toBe("info");
  });
  it("every severity has a label in both locales", () => {
    for (const s of SEVERITIES) {
      expect((en as Record<string, string>)[`severity.${s}`], s).toBeTruthy();
      expect((zh as Record<string, string>)[`severity.${s}`], s).toBeTruthy();
    }
  });
});

describe("executionStatusLabel", () => {
  it("a status the backend writes reads as its locale key; an unknown one stays as the raw value", () => {
    const t = (k: string) => `<${k}>`;
    expect(["pending", "running", "succeeded", "failed", "rolled_back", "aborted"].map((s) => executionStatusLabel(s, t)))
      .toEqual(["<execution.status.pending>", "<execution.status.running>", "<execution.status.succeeded>",
                "<execution.status.failed>", "<execution.status.rolled_back>", "<execution.status.aborted>"]);
    expect(executionStatusLabel("exploded", t)).toBe("exploded");
  });
});

describe("inFlightAutoRun (final review C1 — mirrors pipeline_service.plan_run_in_flight)", () => {
  let n = 0;
  const ev = (event_type: string, created_at: string, detail: unknown = null) =>
    ({ id: ++n, event_type, stage: "execution", status: "x", detail, actor: "system", duration_ms: null, created_at,
       trace_id: null }) as PipelineEvent;
  const now = Date.parse("2026-10-05T10:00:00Z");
  const at = (min: number) => new Date(now - min * 60_000).toISOString().replace("Z", ""); // the backend's naive UTC
  const opts = { timeoutSeconds: 1800, now };

  it("the newest start naming the plan, with no completion after it → its start time", () => {
    expect(inFlightAutoRun([ev("execution_started", at(5), { plan_id: 3 })], 3, opts)).toEqual({ startedAt: at(5) });
  });
  it("a completion after the start (succeeded, failed or a plan-less one on the issue) ends it", () => {
    for (const detail of [{ plan_id: 3, verification: "passed" }, { plan_id: 3 }, null])
      expect(inFlightAutoRun([ev("execution_started", at(5), { plan_id: 3 }), ev("execution_completed", at(1), detail)], 3, opts)).toBeNull();
  });
  it("a completion older than the newest start does not end it; the events need not arrive sorted", () => {
    const events = [ev("execution_started", at(2), { plan_id: 3 }), ev("execution_started", at(20), { plan_id: 3 }),
                    ev("execution_completed", at(10), { plan_id: 3 })];
    expect(inFlightAutoRun(events, 3, opts)).toEqual({ startedAt: at(2) });
  });
  it("stale beyond the executor timeout; without a known timeout it is not bounded", () => {
    const events = [ev("execution_started", at(31), { plan_id: 3 })];
    expect(inFlightAutoRun(events, 3, opts)).toBeNull();
    expect(inFlightAutoRun(events, 3, { now })).toEqual({ startedAt: at(31) });
  });
  it("another plan's start, a malformed detail, no plan, no events → null", () => {
    expect(inFlightAutoRun([ev("execution_started", at(5), { plan_id: 4 })], 3, opts)).toBeNull();
    for (const detail of ["{\"plan_id\":3}", [3], null])
      expect(inFlightAutoRun([ev("execution_started", at(5), detail)], 3, opts)).toBeNull();
    expect(inFlightAutoRun([ev("execution_started", at(5), { plan_id: 3 })], null, opts)).toBeNull();
    expect(inFlightAutoRun(undefined, 3, opts)).toBeNull();
  });
});
