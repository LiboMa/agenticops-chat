import { describe, it, expect } from "vitest";
import type { FixExecution, FixPlan, PipelineEvent, RCAResult } from "@/api/types";
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
  it("approved, no run row and no auto-run on the timeline → retry is the primary and the reason says so", () => {
    const plan = { id: 1, status: "approved", created_at: "2026-10-03T09:00:00" } as FixPlan;
    const m = issueDetailModel({ issue: { status: "fix_approved" }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: [],
                                 timeline: [] });
    expect(m.primaryKey).toBe("workitem.primary.retryExecution");
    expect(m.reason).toEqual({ key: "workitem.reason.notQueued" });
    expect(m.menu).not.toContain("retryExecution");
  });
  it("terminal: no primary; menu has reopen only", () => {
    const m = issueDetailModel({ issue: { status: "dismissed" }, rca: null, threshold: 0.6, plans: [], executions: [] });
    expect([m.primaryKey, m.menu]).toEqual([null, ["reopen"]]);
  });

  it("runs still loading (executions undefined) at fix_approved / fix_executed: a neutral state, no reason, no primary", () => {
    const plan = { id: 1, status: "approved", created_at: "2026-10-03T09:00:00" } as FixPlan;
    for (const status of ["fix_approved", "fix_executed"] as const) {
      const m = issueDetailModel({ issue: { status }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: undefined });
      expect([m.statusKey, m.primaryKey, m.reason, m.waitingKey, m.pendingRun], status)
        .toEqual(["workitem.sub.loadingRuns", null, null, null, null]);
      expect(m.tone).toBe("info");
    }
  });
  it("runs failed to load at fix_executed: says so, never 'finished without a verdict'; no primary", () => {
    const m = issueDetailModel({ issue: { status: "fix_executed" }, rca: rcaI1, threshold: 0.6, plans: [], executions: undefined,
                                 runsFailed: true });
    expect([m.statusKey, m.primaryKey, m.reason]).toEqual(["workitem.sub.runsUnavailable", null, null]);
    expect(m.tone).toBe("warn");
    // a status that does not depend on its runs is unaffected
    expect(issueDetailModel({ issue: { status: "fix_planned" }, rca: rcaI1, threshold: 0.6, plans: [], executions: undefined,
                              runsFailed: true }).statusKey).toBe("workitem.sub.awaitingApproval");
  });
  it("a failed refetch with runs already loaded: the cached runs still decide the state (runsFailed alone hides nothing)", () => {
    const running = run({ status: "running" });
    const input = { issue: { status: "fix_executing" as const }, rca: rcaI1, threshold: 0.6, plans: [], executions: [running] };
    const cached = issueDetailModel({ ...input, runsFailed: true });
    expect(cached.statusKey).toBe(issueDetailModel(input).statusKey);
    expect(cached.statusKey).not.toBe("workitem.sub.runsUnavailable");
    expect(cached.menu).toContain("cancelRun");
  });
  it("the menu never repeats the primary's Rerun RCA, and never offers plan generation without an RCA", () => {
    const none = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: null, threshold: 0.6, plans: [], executions: [] });
    expect(none.primaryKey).toBe("workitem.primary.rerunRca");
    expect(none.menu).toEqual(["markResolved", "dismiss"]);
    const rejected = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: { ...rcaI1, human_verdict: "incorrect" } as RCAResult,
                                        threshold: 0.6, plans: [], executions: [] });
    expect(rejected.menu).toEqual(["skipReviewGeneratePlan", "markResolved", "dismiss"]);
    const loading = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: undefined, threshold: 0.6, plans: [], executions: [] });
    expect(loading.menu).toEqual(["runRca", "markResolved", "dismiss"]);
  });
  it("quiet flags: the latest run's error / verdict reason is hidden only when it IS the status line's sentence", () => {
    const rcaOk = { ...rcaI1, confidence: 0.9, evidence_verified: true } as RCAResult;
    const at = (ex: FixExecution, status: "root_cause_identified" | "fix_executed" = "root_cause_identified") =>
      issueDetailModel({ issue: { status }, rca: rcaOk, threshold: 0.6, plans: [], executions: [ex] });
    // evaluate() copies a failed run's error into verification_reason: one sentence, both places quiet
    const same = at(run({ status: "failed", verification_status: "failed", error_message: "ssm timeout", verification_reason: "ssm timeout" }));
    expect([same.quietRunError, same.quietAcceptReason]).toEqual([true, true]);
    // the status line shows the post-check reason; a different error stays visible in the run's evidence
    const differ = at(run({ status: "failed", verification_status: "failed", error_message: "exit 2", verification_reason: "post-check 2 failed" }));
    expect([differ.quietRunError, differ.quietAcceptReason]).toEqual([false, true]);
    // a rejected acceptance (stamped failed + the note): the note is the sentence, so neither the error nor the verdict reason is quiet
    const note = at(run({ verification_status: "failed", verification_reason: "the plan has no post-checks",
                          acceptance_note: "pods still crash-looping" }));
    expect([note.reason, note.quietRunError, note.quietAcceptReason]).toEqual([{ text: "pods still crash-looping" }, false, false]);
    // awaiting acceptance: the verdict reason is the sentence
    const pend = at(run({ verification_status: "pending_acceptance", verification_reason: "the plan has no post-checks" }), "fix_executed");
    expect([pend.quietRunError, pend.quietAcceptReason]).toEqual([false, true]);
    // a key reason (not the run's own text): nothing is quiet
    const gate = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: rcaI1, threshold: 0.6, plans: [],
                                    executions: [run({ error_message: "x", verification_reason: "x" })] });
    expect([gate.quietRunError, gate.quietAcceptReason]).toEqual([false, false]);
  });
});

describe("issueDetailModel — an approval's auto-run (final review C1) and an RCA that failed to load (I1)", () => {
  const plan = { id: 1, status: "approved", created_at: "2026-10-05T09:00:00" } as FixPlan;
  const now = Date.parse("2026-10-05T10:00:00Z");
  let n = 0;
  const ev = (event_type: string, created_at: string, detail: Record<string, unknown> | null) =>
    ({ id: ++n, event_type, stage: "execution", status: "x", detail, actor: "system", duration_ms: null, created_at,
       trace_id: null }) as PipelineEvent;
  const started = ev("execution_started", "2026-10-05T09:58:00", { plan_id: 1, executor: "agent:executor" });
  const at = (x: Partial<Parameters<typeof issueDetailModel>[0]>) => issueDetailModel({
    issue: { status: "fix_approved" }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: [], timeline: [started],
    executorTimeout: 1800, now, ...x });

  it("right after «Approve & run»: running, waiting for the executor, no primary, no 'not queued'; retry only in ⋯", () => {
    const m = at({});
    expect([m.statusKey, m.waitingKey, m.primaryKey, m.reason, m.tone])
      .toEqual(["workitem.sub.executing", "workitem.wait.executor", null, null, "info"]);
    expect(m.autoRun).toEqual({ startedAt: "2026-10-05T09:58:00" });
    expect(m.menu).toContain("retryExecution");
    expect(m.menu).not.toContain("cancelRun"); // an auto-run has no row to cancel
  });
  it("the run completed (or failed) after it started → not queued + retry primary again", () => {
    const done = ev("execution_completed", "2026-10-05T09:59:00", { plan_id: 1 });
    const m = at({ timeline: [started, done] });
    expect([m.statusKey, m.primaryKey]).toEqual(["workitem.sub.notQueued", "workitem.primary.retryExecution"]);
    expect(m.autoRun).toBeNull();
  });
  it("a start older than the executor timeout is stale: not queued", () => {
    expect(at({ now: now + 3600_000 }).statusKey).toBe("workitem.sub.notQueued");
  });
  it("another plan's start does not count", () => {
    expect(at({ timeline: [ev("execution_started", "2026-10-05T09:58:00", { plan_id: 2 })] }).statusKey).toBe("workitem.sub.notQueued");
  });
  it("the timeline not loaded yet / failed: a neutral state, never 'not queued' + retry", () => {
    const loading = at({ timeline: undefined });
    expect([loading.statusKey, loading.primaryKey, loading.reason, loading.waitingKey]).toEqual(["workitem.sub.loadingRuns", null, null, null]);
    const failed = at({ timeline: undefined, timelineFailed: true });
    expect([failed.statusKey, failed.primaryKey, failed.tone]).toEqual(["workitem.sub.runsUnavailable", null, "warn"]);
    // a pending row decides on its own: the timeline is not needed
    expect(at({ timeline: undefined, executions: [run({ status: "pending" })] }).statusKey).toBe("workitem.sub.executing");
  });
  it("I1: the RCA failed to load at root_cause_identified — says so; never 'no RCA' + Rerun RCA", () => {
    const m = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: undefined, rcaFailed: true, threshold: 0.6,
                                 plans: [], executions: [] });
    expect([m.statusKey, m.primaryKey, m.reason, m.waitingKey, m.tone])
      .toEqual(["workitem.sub.rcaUnavailable", null, null, null, "warn"]);
    // still loading: the neutral list mode; a failed run decides without the RCA
    expect(issueDetailModel({ issue: { status: "root_cause_identified" }, rca: undefined, threshold: 0.6, plans: [], executions: [] })
      .statusKey).toBe("workitem.sub.reviewOrPlan");
    const failedRun = run({ status: "failed", verification_status: "failed", verification_reason: "post-check 2 failed" });
    expect(issueDetailModel({ issue: { status: "root_cause_identified" }, rca: undefined, rcaFailed: true, threshold: 0.6,
                              plans: [], executions: [failedRun] }).statusKey).toBe("workitem.sub.needsNewPlan");
    // a stored "none" is still none
    expect(issueDetailModel({ issue: { status: "root_cause_identified" }, rca: null, threshold: 0.6, plans: [], executions: [] })
      .reason).toEqual({ key: "workitem.reason.noRca" });
  });
});
