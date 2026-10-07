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
    expect(m.menu).toEqual(["runRca", "skipReviewGeneratePlan", "markResolved", "dismiss", "askAgent"]);
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
    expect([m.primaryKey, m.menu]).toEqual([null, ["reopen", "askAgent"]]);
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
    expect(none.menu).toEqual(["markResolved", "dismiss", "askAgent"]);
    const rejected = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: { ...rcaI1, human_verdict: "incorrect" } as RCAResult,
                                        threshold: 0.6, plans: [], executions: [] });
    expect(rejected.menu).toEqual(["skipReviewGeneratePlan", "markResolved", "dismiss", "askAgent"]);
    const loading = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: undefined, threshold: 0.6, plans: [], executions: [] });
    expect(loading.menu).toEqual(["runRca", "markResolved", "dismiss", "askAgent"]);
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
  const now = Date.parse("2026-10-05T10:00:00Z");
  const iso = (ms: number) => new Date(ms).toISOString().replace("Z", ""); // the backend's naive UTC
  const A = Date.parse("2026-10-05T09:57:59Z"); // the plan's own approval
  const GRACE = 30_000;
  const plan = { id: 1, status: "approved", created_at: "2026-10-05T09:00:00", approved_at: iso(A) } as FixPlan;
  let n = 0;
  const ev = (event_type: string, created_at: string, detail: Record<string, unknown> | null) =>
    ({ id: ++n, event_type, stage: "execution", status: "x", detail, actor: "system", duration_ms: null, created_at,
       trace_id: null }) as PipelineEvent;
  const started = ev("execution_started", "2026-10-05T09:58:00", { plan_id: 1, executor: "agent:executor" });
  const moved = (to: string, created_at: string) => ev("status_changed", created_at, { from: "x", to, reason: "r" });
  const at = (x: Partial<Parameters<typeof issueDetailModel>[0]>) => issueDetailModel({
    issue: { status: "fix_approved" }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: [], timeline: [started],
    timelineFetchedAt: now, executorTimeout: 1800, now, ...x });
  const pick = (m: ReturnType<typeof issueDetailModel>) => [m.statusKey, m.primaryKey, m.reason, m.waitingKey];
  const CHECKING = ["workitem.sub.checkingRun", null, null, null];
  const NOT_QUEUED = ["workitem.sub.notQueued", "workitem.primary.retryExecution", { key: "workitem.reason.notQueued" }, "workitem.wait.you"];

  it("right after «Approve & run»: running, waiting for the executor, no primary, no 'not queued'; retry only in ⋯", () => {
    const m = at({});
    expect([m.statusKey, m.waitingKey, m.primaryKey, m.reason, m.tone])
      .toEqual(["workitem.sub.executing", "workitem.wait.executor", null, null, "info"]);
    expect(m.autoRun).toEqual({ startedAt: "2026-10-05T09:58:00" });
    expect(m.menu).toContain("retryExecution");
    expect(m.menu).not.toContain("cancelRun"); // an auto-run has no row to cancel
    expect(m.recheckAt).toBeNull();
  });
  it("the run completed (or failed) after it started → not queued + retry primary again", () => {
    const m = at({ timeline: [started, ev("execution_completed", "2026-10-05T09:59:00", { plan_id: 1 })] });
    expect(pick(m)).toEqual(NOT_QUEUED);
    expect(m.autoRun).toBeNull();
  });
  it("a start older than the executor timeout is stale: not queued", () => {
    expect(at({ now: now + 3600_000, timelineFetchedAt: now + 3600_000 }).statusKey).toBe("workitem.sub.notQueued");
  });
  it("another plan's start does not count", () => {
    expect(at({ timeline: [ev("execution_started", "2026-10-05T09:58:00", { plan_id: 2 })] }).statusKey).toBe("workitem.sub.notQueued");
  });

  it("C1(c): no start seen in a timeline fetched before the plan's approval + 30 s → checking, recheck at that moment", () => {
    const m = at({ timeline: [], timelineFetchedAt: A + 1_000, now: A + 5_000 });
    expect(pick(m)).toEqual(CHECKING);
    expect([m.tone, m.recheckAt]).toEqual(["info", A + GRACE]);
    // never stuck: «Retry execution» stays in ⋯ while checking (the backend refuses a duplicate with 409)
    expect(m.menu).toContain("retryExecution");
  });
  it("C1(c): the boundary — a timeline fetched at exactly approval + 30 s with no start says not queued", () => {
    expect(pick(at({ timeline: [], timelineFetchedAt: A + GRACE, now: A + GRACE }))).toEqual(NOT_QUEUED);
    expect(at({ timeline: [], timelineFetchedAt: A + GRACE, now: A + GRACE }).recheckAt).toBeNull();
    expect(pick(at({ timeline: [], timelineFetchedAt: A + GRACE - 1, now: A + GRACE }))).toEqual(CHECKING);
  });
  it("C1(c): a run of this plan that ended after its approval needs no wait", () => {
    const ended = [ev("execution_started", iso(A + 1_000), { plan_id: 1 }), ev("execution_completed", iso(A + 2_000), { plan_id: 1 })];
    expect(pick(at({ timeline: ended, timelineFetchedAt: A + 3_000, now: A + 3_000 }))).toEqual(NOT_QUEUED);
  });
  it("C1(c): a re-approval (withdraw + approve writes no new status move) is anchored on the new plan's approved_at", () => {
    const B = now - 5_000;
    const planB = { id: 2, status: "approved", created_at: "2026-10-05T09:30:00", approved_at: iso(B) } as FixPlan;
    const old = { id: 1, status: "rejected", created_at: "2026-10-05T09:00:00", approved_at: iso(A) } as FixPlan;
    // the issue moved into fix_approved long ago (plan 1), and plan 1 never ran
    const m = at({ plans: [planB, old], timeline: [moved("fix_approved", iso(A))] });
    expect(pick(m)).toEqual(CHECKING);
    expect(m.recheckAt).toBe(B + GRACE);
    // plan 1's old run does not count for plan 2
    const oldRun = [ev("execution_started", iso(A + 1_000), { plan_id: 1 }), ev("execution_completed", iso(A + 2_000), { plan_id: 1 })];
    expect(at({ plans: [planB, old], timeline: oldRun }).statusKey).toBe("workitem.sub.checkingRun");
  });
  it("C1(c): a pre-2.6.1 issue (no status moves) is anchored on approved_at too; a plan without approved_at has no anchor", () => {
    const recent = { ...plan, approved_at: iso(now - 5_000) };
    expect(pick(at({ plans: [recent], timeline: [] }))).toEqual(CHECKING);
    expect(pick(at({ plans: [recent], timeline: [], timelineFetchedAt: now + GRACE, now: now + GRACE }))).toEqual(NOT_QUEUED);
    expect(pick(at({ plans: [{ ...plan, approved_at: null }], timeline: [] }))).toEqual(NOT_QUEUED);
  });
  it("the timeline not loaded yet / failed: a neutral state that names what is missing, never 'not queued' + retry", () => {
    const loading = at({ timeline: undefined, timelineFetchedAt: 0 });
    expect([...pick(loading), loading.recheckAt]).toEqual([...CHECKING, null]);
    const failed = at({ timeline: undefined, timelineFetchedAt: 0, timelineFailed: true });
    expect([failed.statusKey, failed.primaryKey, failed.tone, failed.recheckAt]).toEqual(["workitem.sub.runStateUnavailable", null, "warn", null]);
    expect(failed.menu).toContain("retryExecution");
    // a failed poll over a copy fetched inside the grace: the same, never the stale "not queued"
    expect(at({ timeline: [], timelineFetchedAt: A + 1_000, now: A + 60_000, timelineFailed: true }).statusKey)
      .toBe("workitem.sub.runStateUnavailable");
    // a pending row decides on its own: the timeline is not needed
    expect(at({ timeline: undefined, executions: [run({ status: "pending" })] }).statusKey).toBe("workitem.sub.executing");
    // the runs themselves unknown keep their own wording
    expect(at({ executions: undefined }).statusKey).toBe("workitem.sub.loadingRuns");
  });
  it("the plans not loaded yet / failed: the auto-run cannot be matched to a plan — neutral too", () => {
    expect(pick(at({ plans: undefined }))).toEqual(CHECKING);
    expect(at({ plans: undefined, plansFailed: true }).statusKey).toBe("workitem.sub.runStateUnavailable");
    expect(at({ plans: undefined }).menu).not.toContain("retryExecution"); // no plan to retry
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
