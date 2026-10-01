import { describe, it, expect } from "vitest";
import { activeChangePlan, changeHeadline, externalRefLink, isHintResolved, planStepMarks, policySummary, toPipelineEvents } from "@/lib/changeDetail";
import type { ChangeRequest, ChangeTarget, ChangeTimelineEntry, FixExecution, FixPlan } from "@/api/types";

type Tgt = Pick<ChangeTarget, "resource_id" | "hint">;

describe("isHintResolved (R2)", () => {
  const targets: Tgt[] = [{ resource_id: "i-0abc", hint: "web-server" }];
  it.each([
    ["exact resource_id match", "i-0abc", targets, true],
    ["exact hint match", "web-server", targets, true],
    ["strip + case-insensitive resource_id", " I-0ABC ", targets, true],
    ["a hint matching nothing", "nope", targets, false],
    ["an empty target list", "i-0abc", [] as Tgt[], false],
    ["a missing-hint target that matches on id", "i-0abc", [{ resource_id: "i-0abc" }] as Tgt[], true],
    ["a missing-hint target with no match (no throw)", "web-server", [{ resource_id: "i-0abc" }] as Tgt[], false],
  ] as [string, string, Tgt[], boolean][])("%s", (_label, hint, tgts, expected) => {
    expect(isHintResolved(hint, tgts)).toBe(expected);
  });
});

describe("toPipelineEvents (R2)", () => {
  it("maps an event row with all fields present", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: "2026-09-20T00:00:00", kind: "event", type: "change_requested", actor: "alice", status: "started", stage: "intake", detail: { note: "hi" } },
    ];
    expect(toPipelineEvents(entries)).toEqual([
      { id: 0, event_type: "change_requested", stage: "intake", status: "started", actor: "alice", duration_ms: null, created_at: "2026-09-20T00:00:00", trace_id: null, detail: { note: "hi" } },
    ]);
  });

  it("fills defaults: status null → '', actor null → 'system', ts null → '', stage null → ''", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: null, kind: "audit", type: "authz.denied", actor: null, status: null, stage: null, detail: null },
    ];
    expect(toPipelineEvents(entries)).toEqual([
      { id: 0, event_type: "authz.denied", stage: "", status: "", actor: "system", duration_ms: null, created_at: "", trace_id: null, detail: null },
    ]);
  });

  it("passes an audit stage through and stringifies nested object values", () => {
    const entries: ChangeTimelineEntry[] = [
      { ts: "t", kind: "audit", type: "policy", actor: "sys", status: "completed", stage: "audit", detail: { policy_decision: { a: 1 }, reason: "ok" } },
    ];
    const out = toPipelineEvents(entries);
    expect(out[0].stage).toBe("audit");
    expect(out[0].detail).toEqual({ policy_decision: JSON.stringify({ a: 1 }), reason: "ok" });
  });

  it("wraps a legacy string detail as { detail }", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: "legacy" }]);
    expect(out[0].detail).toEqual({ detail: "legacy" });
  });

  it("wraps an array detail and JSON-stringifies it", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: [1, 2, 3] }]);
    expect(out[0].detail).toEqual({ detail: JSON.stringify([1, 2, 3]) });
  });

  it("null detail → null", () => {
    const out = toPipelineEvents([{ ts: "t", kind: "event", type: "x", actor: "a", status: "s", stage: "st", detail: null }]);
    expect(out[0].detail).toBeNull();
  });

  it("ids equal the array indexes", () => {
    const rows: ChangeTimelineEntry[] = [0, 1, 2].map((n) => ({ ts: "t", kind: "event", type: `e${n}`, actor: "a", status: "s", stage: "st", detail: null }));
    expect(toPipelineEvents(rows).map((e) => e.id)).toEqual([0, 1, 2]);
  });
});

describe("policySummary (R2)", () => {
  it("reads a full payload", () => {
    expect(policySummary({ reasons: ["r1", "r2"], escalated_from: "L1", effective_risk_level: "L3" })).toEqual({
      reasons: ["r1", "r2"],
      escalatedFrom: "L1",
      effectiveRisk: "L3",
    });
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
  ] as [string, Record<string, unknown> | null | undefined][])("%s → all empty", (_l, pd) => {
    expect(policySummary(pd)).toEqual({ reasons: [], escalatedFrom: null, effectiveRisk: null });
  });

  it("reasons that is not an array → []", () => {
    expect(policySummary({ reasons: "nope" }).reasons).toEqual([]);
  });

  it("keeps only string reasons, dropping non-strings", () => {
    expect(policySummary({ reasons: ["a", 1, "b", null] }).reasons).toEqual(["a", "b"]);
  });

  it("escalated_from empty string → null", () => {
    expect(policySummary({ escalated_from: "" }).escalatedFrom).toBeNull();
  });

  it("drops reasons already shown in review_reasons (no duplicated list)", () => {
    expect(policySummary({ reasons: ["risk_level=L1", "extra"] }, ["sre note", "risk_level=L1"]).reasons).toEqual([
      "extra",
    ]);
  });
});

type HeadlineInput = Parameters<typeof changeHeadline>[0];
function cr(extra: Partial<ChangeRequest>): HeadlineInput {
  return { status: "draft", needs_review_reason: null, review_reasons: [], rejection_reason: null, ...extra };
}
function run(extra: Partial<FixExecution>): FixExecution {
  return {
    id: 5, fix_plan_id: 3, health_issue_id: null, status: "succeeded", started_at: null, completed_at: null,
    executed_by: "web:anonymous", pre_check_results: [], step_results: [], post_check_results: [],
    rollback_results: [], error_message: null, duration_ms: 0, verification_status: null,
    verification_reason: null, accepted_by: null, accepted_at: null, acceptance_note: null,
    created_at: "2026-09-28T02:00:00", ...extra,
  };
}

describe("changeHeadline", () => {
  it("an executed change waiting for acceptance reads its needs_review_reason, the acceptor, and Accept", () => {
    const pending = run({ verification_status: "pending_acceptance", verification_reason: "no post-checks declared" });
    expect(changeHeadline(cr({ status: "needs_review", needs_review_reason: "no post-checks declared" }), pending))
      .toEqual({ reason: "no post-checks declared", todo: "accept", action: "accept" });
  });

  it("falls back to the pending run's verification reason — the one IssueDetail shows — on an older row", () => {
    const pending = run({ verification_status: "pending_acceptance", verification_reason: "post-check 2 failed" });
    expect(changeHeadline(cr({ status: "needs_review" }), pending).reason).toBe("post-check 2 failed");
  });

  it("names the next actor and the primary action for each open status", () => {
    expect(changeHeadline(cr({ status: "draft" }), null)).toEqual({ reason: null, todo: "startReview", action: "review" });
    expect(changeHeadline(cr({ status: "under_review" }), null)).toEqual({ reason: null, todo: "review", action: null });
    expect(changeHeadline(cr({ status: "planned" }), null)).toEqual({ reason: null, todo: "approve", action: "approve" });
    expect(changeHeadline(cr({ status: "approved" }), null)).toEqual({ reason: null, todo: "execute", action: "execute" });
    expect(changeHeadline(cr({ status: "executing" }), null)).toEqual({ reason: null, todo: "executing", action: null });
  });

  it("a clarification request reads the reviewer's questions", () => {
    expect(changeHeadline(cr({ status: "needs_clarification", review_reasons: ["which cluster?", "when?"] }), null))
      .toEqual({ reason: "which cluster? · when?", todo: "clarify", action: "clarify" });
  });

  it("a closed change has no to-do; rejected / cancelled read the rejection reason", () => {
    expect(changeHeadline(cr({ status: "rejected", rejection_reason: "too risky" }), null))
      .toEqual({ reason: "too risky", todo: null, action: null });
    expect(changeHeadline(cr({ status: "cancelled", rejection_reason: "not needed" }), null).reason).toBe("not needed");
    expect(changeHeadline(cr({ status: "completed" }), run({ verification_status: "passed" })))
      .toEqual({ reason: null, todo: null, action: null });
  });

  it("a failed change reads the human verdict's note, else the verification reason, else the run's error", () => {
    expect(changeHeadline(cr({ status: "failed" }), run({ acceptance_note: "pods still crash", verification_reason: "x" })).reason)
      .toBe("pods still crash");
    expect(changeHeadline(cr({ status: "rolled_back" }), run({ status: "rolled_back", verification_reason: "rolled back" })).reason)
      .toBe("rolled back");
    expect(changeHeadline(cr({ status: "failed" }), run({ status: "failed", error_message: "timeout" })).reason).toBe("timeout");
    expect(changeHeadline(cr({ status: "failed" }), null).reason).toBeNull();
  });
});

describe("planStepMarks", () => {
  it("marks each plan step the plan added or changed, and lists the requested steps it dropped", () => {
    const m = planStepMarks({
      added: [{ plan_step: 3, command: "kubectl rollout status deploy/web" }],
      removed: [{ proposed_step: 4, command: "rm -rf /tmp/cache" }],
      modified: [{ proposed_step: 1, plan_step: 1, proposed: "kubectl scale --replicas=5", plan: "kubectl scale --replicas=3" }],
      unchanged: 1,
    })!;
    expect(m.byPlanStep.get(1)).toEqual({ kind: "modified", proposed: "kubectl scale --replicas=5" });
    expect(m.byPlanStep.get(2)).toBeUndefined();
    expect(m.byPlanStep.get(3)).toEqual({ kind: "added" });
    expect(m.removed).toEqual([{ proposed_step: 4, command: "rm -rf /tmp/cache" }]);
    expect(m).toMatchObject({ added: 1, modified: 1, unchanged: 1, identical: false });
  });

  it("an identical plan is identical; a request with no steps of its own has no diff", () => {
    expect(planStepMarks({ added: [], removed: [], modified: [], unchanged: 2 }))
      .toMatchObject({ identical: true, removed: [], unchanged: 2 });
    expect(planStepMarks(null)).toBeNull();
  });
});

describe("externalRefLink", () => {
  it("labels the ticket by system and id, with its link and the external requester", () => {
    expect(externalRefLink({ system: "jira", ticket_id: "OPS-12", url: "https://jira.example/OPS-12", requested_by: "alice" }))
      .toEqual({ label: "jira OPS-12", url: "https://jira.example/OPS-12", requestedBy: "alice" });
  });

  it("links only an http(s) URL; no ref, no link", () => {
    expect(externalRefLink({ system: "sn", ticket_id: "CHG1", url: "javascript:alert(1)" }))
      .toEqual({ label: "sn CHG1", url: null, requestedBy: null });
    expect(externalRefLink({ system: "sn", ticket_id: "CHG1" })?.url).toBeNull();
    expect(externalRefLink(null)).toBeNull();
  });
});

describe("activeChangePlan", () => {
  it("is the plan an approve acts on: the newest not executed/failed/rejected, as the backend's active_plan_for", () => {
    const plan = (id: number, status: FixPlan["status"]) => ({ id, status }) as FixPlan;
    // plans come newest first: a newer rejected plan above the older one still awaiting approval
    expect(activeChangePlan([plan(9, "rejected"), plan(7, "pending_approval")])?.id).toBe(7);
    // all terminal: the newest, for display only
    expect(activeChangePlan([plan(9, "rejected"), plan(7, "executed")])?.id).toBe(9);
    expect(activeChangePlan([])).toBeNull();
  });
});
