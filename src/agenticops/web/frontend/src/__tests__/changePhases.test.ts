import { describe, it, expect } from "vitest";
import type { ChangeRequestDetail, FixExecution } from "@/api/types";
import { changePhases } from "@/lib/changePhases";
import { changeDetailModel } from "@/lib/changeDetailModel";

const C = (status: string, extra: Record<string, unknown> = {}) =>
  ({ status, review_verdict: null, approved_at: null, ...extra }) as Parameters<typeof changePhases>[0];
const pick = (r: ReturnType<typeof changePhases>) => [r.current, r.sub, r.waitingFor, r.primary];
const ids = (r: ReturnType<typeof changePhases>) => r.phases.map((p) => `${p.id}:${p.state}`);
// a change detail with nothing on it but its status (the model's other inputs empty)
const bare = (status: string) => ({ id: 1, status, review_verdict: null, approved_at: null, needs_review_reason: null,
  review_reasons: [], rejection_reason: null, plans: [], executions: [], policy_decision: null }) as unknown as ChangeRequestDetail;

describe("changePhases — spec §4 change table", () => {
  it("open states", () => {
    expect(pick(changePhases(C("draft")))).toEqual(["request", "draft", "requester", "startReview"]);
    expect(pick(changePhases(C("under_review")))).toEqual(["review", "reviewing", "sre_agent", null]);
    expect(pick(changePhases(C("needs_clarification")))).toEqual(["review", "needsClarification", "requester", "answerReviewer"]);
    expect(pick(changePhases(C("planned")))).toEqual(["run", "awaitingApproval", "approver", "approveAndRun"]);
    expect(pick(changePhases(C("approved")))).toEqual(["run", "notQueued", "you", "retryExecution"]);
    expect(pick(changePhases(C("executing")))).toEqual(["run", "executing", "executor", null]);
    expect(pick(changePhases(C("needs_review")))).toEqual(["accept", "awaitingAcceptance", "acceptor", "markCompleted"]);
    expect(ids(changePhases(C("planned")))).toEqual(["request:done", "review:done", "plan:done", "run:current", "accept:future"]);
  });
  it("completed: all five done, no primary", () => {
    const r = changePhases(C("completed"));
    expect(pick(r)).toEqual(["accept", "completed", null, null]);
    expect(ids(r)).toEqual(["request:done", "review:done", "plan:done", "run:done", "accept:done"]);
  });
  it("a bad ending ends the list at the phase it ended on (no Completed after Failed); next step: copy as new", () => {
    expect(ids(changePhases(C("failed")))).toEqual(["request:done", "review:done", "plan:done", "run:failed"]);
    expect(pick(changePhases(C("failed")))).toEqual(["run", "failed", null, "copyAsNew"]);
    expect(ids(changePhases(C("rolled_back")))).toEqual(["request:done", "review:done", "plan:done", "run:failed"]);
    expect(ids(changePhases(C("rejected")))).toEqual(["request:done", "review:failed"]);
    expect(ids(changePhases(C("rejected", { review_verdict: "approved_for_planning" })))).toEqual(
      ["request:done", "review:done", "plan:done", "run:failed"]);
    expect(ids(changePhases(C("cancelled")))).toEqual(["request:failed"]);
    expect(ids(changePhases(C("cancelled", { review_verdict: "needs_clarification" })))).toEqual(["request:done", "review:failed"]);
    expect(ids(changePhases(C("cancelled", { approved_at: "2026-10-03T09:55:56" })))).toEqual(
      ["request:done", "review:done", "plan:done", "run:failed"]);
    for (const s of ["failed", "rolled_back", "rejected", "cancelled"]) expect(changePhases(C(s)).terminal, s).toBe(true);
  });
});

describe("changeDetailModel — C#1 (failed at pre-check #1): the failure sentence appears exactly once", () => {
  const sentence = "Pre-check #1 FAILED: Deployment frontend reports 0 ready replicas (expected 3/3).";
  const run = { id: 1, fix_plan_id: 1, status: "aborted", verification_status: "failed", verification_reason: sentence,
                error_message: sentence, acceptance_note: null, created_at: "2026-10-03T09:56:11" } as FixExecution;
  const cr = { id: 1, status: "failed", review_verdict: "approved_for_planning", approved_at: "2026-10-03T09:55:56",
               needs_review_reason: null, review_reasons: [], rejection_reason: null, plans: [], executions: [run],
               policy_decision: null } as unknown as ChangeRequestDetail;
  it("the status line carries it; the accept card points at the run instead of repeating it", () => {
    const m = changeDetailModel(cr);
    expect(m.reason).toBe(sentence);
    expect(m.acceptNote).toEqual({ key: "workitem.accept.systemFailed", params: { n: "1" } });
    expect(m.primaryKey).toBe("workitem.primary.copyAsNew");
    const { runs, latestRun, ...shown } = m; // the runs are evidence rows, rendered without their sentence
    expect(JSON.stringify(shown).split(sentence).length - 1).toBe(1);
    expect(runs).toHaveLength(1);
    expect(latestRun?.id).toBe(1);
  });
  it("quietRunError: the latest run's error box is left out only when it IS the status line's sentence", () => {
    expect(changeDetailModel(cr).quietRunError).toBe(true);
    // the reason is the verdict's sentence; a different error stays visible in the run's evidence
    const differ = { ...run, error_message: "exit 2" } as FixExecution;
    expect(changeDetailModel({ ...cr, executions: [differ] }).quietRunError).toBe(false);
    // a rejected acceptance: the note is the sentence, so the run's error is not quiet
    const noted = { ...run, acceptance_note: "pods still crash-looping" } as FixExecution;
    const m = changeDetailModel({ ...cr, executions: [noted] });
    expect([m.reason, m.quietRunError]).toEqual(["pods still crash-looping", false]);
    // no reason on the status line (approved, the run not queued): nothing is quiet, even an empty error
    const bare = { ...run, error_message: null, verification_reason: null } as unknown as FixExecution;
    expect(changeDetailModel({ ...cr, status: "approved", executions: [bare] }).quietRunError).toBe(false);
    expect(changeDetailModel({ ...cr, executions: [] }).quietRunError).toBe(false);
  });
  it("quietReviewReasons: a review's rejection is its reasons joined — the status line says them, ② does not", () => {
    const reasons = ["target is a production database", "no rollback for a drop"];
    const byReview = { ...cr, status: "rejected", review_verdict: "rejected", review_reasons: reasons,
                       rejection_reason: reasons.join("; "), executions: [] } as unknown as ChangeRequestDetail;
    expect([changeDetailModel(byReview).reason, changeDetailModel(byReview).quietReviewReasons])
      .toEqual(["target is a production database; no rollback for a drop", true]);
    // an approver's rejection of the plan: the reason is the approver's, the review's own reasons stay in ②
    const byApprover = { ...byReview, review_verdict: "approved_for_planning", rejection_reason: "not this week" };
    expect(changeDetailModel(byApprover).quietReviewReasons).toBe(false);
    // needs clarification: the reasons are the reviewer's questions, kept next to the answer box
    const asking = { ...byReview, status: "needs_clarification", review_verdict: "needs_clarification",
                     rejection_reason: null } as ChangeRequestDetail;
    expect(changeDetailModel(asking).quietReviewReasons).toBe(false);
  });
  it("acceptNote ('the system judged it failed') only for the system's terminal verdict", () => {
    const note = { key: "workitem.accept.systemFailed", params: { n: "1" } };
    // failed by the system: the run itself did not succeed (C#1, aborted at a pre-check)
    expect(changeDetailModel(cr).acceptNote).toEqual(note);
    expect(changeDetailModel({ ...cr, status: "rolled_back", executions: [{ ...run, status: "rolled_back" } as FixExecution] }).acceptNote)
      .toEqual(note);
    // a succeeded run whose post-check failed waits for a person (on_execution_result → needs_review): no note,
    // the person decides — Mark completed is the primary, and the verdict's reason is the status line's
    const postFail = { ...run, status: "succeeded", error_message: null, verification_reason: "post-check #2 failed: 0/3 ready" } as FixExecution;
    const nr = changeDetailModel({ ...cr, status: "needs_review", needs_review_reason: "post-check #2 failed: 0/3 ready",
                                   executions: [postFail] });
    expect([nr.acceptNote, nr.phase.primary, nr.reason, nr.quietAcceptReason])
      .toEqual([null, "markCompleted", "post-check #2 failed: 0/3 ready", true]);
    // the person's verdict on that run: resolve_review stamps only a pending run, so the failed one keeps no
    // accepted_by — still no "the system judged it" note, whichever way the person decided
    expect(changeDetailModel({ ...cr, status: "completed", executions: [postFail] }).acceptNote).toBeNull();
    expect(changeDetailModel({ ...cr, status: "failed", executions: [postFail] }).acceptNote).toBeNull();
    // a pending run the person marked failed: stamped failed with who judged it
    const judged = { ...postFail, accepted_by: "user:admin", accepted_at: "2026-10-03T10:20:00", acceptance_note: "pods still crash-looping" };
    const m = changeDetailModel({ ...cr, executions: [judged as FixExecution] });
    expect([m.reason, m.acceptNote]).toEqual(["pods still crash-looping", null]);
  });
  it("quietAcceptReason: ⑤ leaves out the verdict reason only when it IS the status line's sentence", () => {
    const pend = { ...run, status: "succeeded", error_message: null, verification_status: "pending_acceptance",
                   verification_reason: "the plan has no post-checks" } as FixExecution;
    // an older row without needs_review_reason: the status line falls back to the run's own reason
    expect(changeDetailModel({ ...cr, status: "needs_review", executions: [pend] }).quietAcceptReason).toBe(true);
    expect(changeDetailModel({ ...cr, status: "needs_review", needs_review_reason: "different", executions: [pend] }).quietAcceptReason)
      .toBe(false);
    // completed: no reason on the status line, so ⑤ shows the verdict's
    expect(changeDetailModel({ ...cr, status: "completed", executions: [{ ...pend, verification_status: "passed" } as FixExecution] })
      .quietAcceptReason).toBe(false);
  });
});

describe("changeDetailModel — every status: primary, menu and tone (copy-as-new exactly once on a closed change)", () => {
  const ROWS: [string, string | null, string[], string][] = [
    ["draft", "startReview", ["cancel"], "info"],
    ["under_review", null, ["restartReview"], "info"],
    ["needs_clarification", "answerReviewer", ["cancel"], "warn"],
    ["planned", "approveAndRun", ["reject", "cancel"], "warn"],
    ["approved", "retryExecution", ["cancel"], "warn"],
    ["executing", null, [], "info"],
    ["needs_review", "markCompleted", ["copyAsNew"], "warn"],
    ["completed", null, ["copyAsNew"], "ok"],
    ["failed", "copyAsNew", [], "bad"],
    ["rolled_back", "copyAsNew", [], "bad"],
    ["rejected", "copyAsNew", [], "bad"],
    ["cancelled", "copyAsNew", [], "bad"],
  ];
  it.each(ROWS)("%s → primary %s, menu %j, tone %s", (status, primary, menu, tone) => {
    const m = changeDetailModel(bare(status));
    expect([m.phase.primary, m.menu, m.tone]).toEqual([primary, menu, tone]);
    const copies = [m.phase.primary, ...m.menu].filter((x) => x === "copyAsNew").length;
    expect(copies).toBe(["draft", "under_review", "needs_clarification", "planned", "approved", "executing"].includes(status) ? 0 : 1);
  });
  it("covers all 12 statuses", () => expect(ROWS).toHaveLength(12));
});

describe("changePhases — edge endings", () => {
  it("a policy block (review passed, then the policy said block) ends the list at ② review, not ④", () => {
    const blocked = C("rejected", { review_verdict: "approved_for_planning", policy_action: "block" });
    expect(ids(changePhases(blocked))).toEqual(["request:done", "review:failed"]);
    expect(ids(changePhases(C("rejected", { review_verdict: "approved_for_planning", policy_action: "require_human" }))))
      .toEqual(["request:done", "review:done", "plan:done", "run:failed"]);
  });
  it("a list that ends at ② with a plan shows that plan read-only inside ② (final review Minor 7)", () => {
    const plan = { id: 7, status: "rejected", created_at: "2026-10-03T09:00:00" };
    const blocked = { ...bare("rejected"), review_verdict: "approved_for_planning", policy_action: "block", plans: [plan] } as unknown as ChangeRequestDetail;
    expect(changeDetailModel(blocked).reviewPlan?.id).toBe(7);
    // no plan to show; or the list reaches ③, which draws it
    expect(changeDetailModel({ ...blocked, plans: [] } as ChangeRequestDetail).reviewPlan).toBeNull();
    expect(changeDetailModel({ ...blocked, policy_action: "require_human" } as ChangeRequestDetail).reviewPlan).toBeNull();
    expect(changeDetailModel({ ...bare("planned"), review_verdict: "approved_for_planning", plans: [plan] } as unknown as ChangeRequestDetail)
      .reviewPlan).toBeNull();
  });
  it("a status outside the union (a newer backend) degrades: no button, nobody waited on, never throws", () => {
    const r = changePhases(C("paused", { review_verdict: "approved_for_planning", approved_at: "2026-10-03T09:55:56" }));
    expect([r.sub, r.waitingFor, r.primary, r.terminal]).toEqual(["unknown", null, null, false]);
    expect(ids(r)).toEqual(["request:done", "review:done", "plan:done", "run:done", "accept:future"]);
    const m = changeDetailModel(bare("paused"));
    expect([m.statusKey, m.primaryKey, m.menu, m.tone]).toEqual(["workitem.sub.unknown", null, [], "info"]);
  });
});
