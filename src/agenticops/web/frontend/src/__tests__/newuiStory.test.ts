import { describe, expect, it } from "vitest";
import type { FixExecution, FixPlan, PipelineEvent } from "@/api/types";
import {
  CHANGE_STEPS, ISSUE_STEPS, changeSpine, closure, issueSpine, lastMove, notesOf, planBasis, planLine, reachedOf, runLine, storyOrigin, storyPath, waitKey,
  type Reached,
} from "@/newui/lib/story";

const all: Reached = { rca: true, plan: true, approved: true, run: true };
const none: Reached = { rca: false, plan: false, approved: false, run: false };
const states = (steps: { state: string }[]) => steps.map((s) => s.state).join(" ");

describe("issueSpine — an issue's six steps: found, diagnosed, planned, approved, run, accepted", () => {
  it("names the steps in order", () => {
    expect(issueSpine("running", none).map((s) => s.id)).toEqual([...ISSUE_STEPS]);
  });

  it("stands at the diagnosis while it runs or waits for a person's call", () => {
    expect(states(issueSpine("running", none))).toBe("done now todo todo todo todo");
    expect(states(issueSpine("needsReview", { ...none, rca: true }))).toBe("done now todo todo todo todo");
    expect(states(issueSpine("rcaRejected", { ...none, rca: true }))).toBe("done bad todo todo todo todo");
  });

  it("stands at the plan when one is to be made, and marks a plan that was sent back", () => {
    expect(states(issueSpine("toGenerate", { ...none, rca: true }))).toBe("done done now todo todo todo");
    expect(states(issueSpine("planRejected", { ...none, rca: true, plan: true }))).toBe("done done bad todo todo todo");
  });

  it("stands at the approval, the run, the acceptance", () => {
    expect(states(issueSpine("awaitingApproval", { ...none, rca: true, plan: true }))).toBe("done done done now todo todo");
    expect(states(issueSpine("executing", all))).toBe("done done done done now todo");
    expect(states(issueSpine("notQueued", all))).toBe("done done done done bad todo");
    expect(states(issueSpine("needsNewPlan", all))).toBe("done done done done bad todo");
    for (const sub of ["awaitingAcceptance", "passed", "unverified"] as const) expect(states(issueSpine(sub, all))).toBe("done done done done done now");
  });

  it("is all done once resolved", () => {
    expect(states(issueSpine("resolved", all))).toBe("done done done done done done");
  });

  it("a dismissed issue stops at the furthest step it had reached", () => {
    expect(states(issueSpine("dismissed", none))).toBe("closed todo todo todo todo todo");
    expect(states(issueSpine("dismissed", { ...none, rca: true }))).toBe("done closed todo todo todo todo");
    expect(states(issueSpine("dismissed", { ...none, rca: true, plan: true }))).toBe("done done closed todo todo todo");
    expect(states(issueSpine("dismissed", all))).toBe("done done done done closed todo");
  });

  it("a status this page does not know shows what there is data for, and claims no current step", () => {
    expect(states(issueSpine("unknown", { ...none, rca: true, plan: true }))).toBe("done done done todo todo todo");
  });
});

describe("changeSpine — a change's six steps: requested, reviewed, planned, approved, run, accepted", () => {
  it("names the steps in order", () => {
    expect(changeSpine("draft", "request", false).map((s) => s.id)).toEqual([...CHANGE_STEPS]);
  });
  it("follows the change's status", () => {
    expect(states(changeSpine("draft", "request", false))).toBe("now todo todo todo todo todo");
    expect(states(changeSpine("reviewing", "review", false))).toBe("done now todo todo todo todo");
    expect(states(changeSpine("needsClarification", "review", false))).toBe("done now todo todo todo todo");
    expect(states(changeSpine("awaitingApproval", "run", false))).toBe("done done done now todo todo");
    expect(states(changeSpine("notQueued", "run", true))).toBe("done done done done bad todo");
    expect(states(changeSpine("executing", "run", true))).toBe("done done done done now todo");
    expect(states(changeSpine("awaitingAcceptance", "accept", true))).toBe("done done done done done now");
    expect(states(changeSpine("completed", "accept", true))).toBe("done done done done done done");
  });
  it("a change that failed or was rolled back ends at the run", () => {
    expect(states(changeSpine("failed", "run", true))).toBe("done done done done bad todo");
    expect(states(changeSpine("rolledBack", "run", true))).toBe("done done done done bad todo");
  });
  it("a rejected or cancelled change is closed where it stopped", () => {
    expect(states(changeSpine("rejected", "review", false))).toBe("done closed todo todo todo todo");
    expect(states(changeSpine("rejected", "run", false))).toBe("done done done closed todo todo");       // the review passed, the approver said no
    expect(states(changeSpine("cancelled", "request", false))).toBe("closed todo todo todo todo todo");
    expect(states(changeSpine("cancelled", "run", false))).toBe("done done done closed todo todo");      // planned, never approved
    expect(states(changeSpine("cancelled", "run", true))).toBe("done done done done closed todo");       // approved, never run
  });
});

describe("waitKey — who the status line says it waits on", () => {
  it("says «you» only when it is on your own list", () => {
    expect(waitKey("approver", true, null)).toBe("wait.you");
    expect(waitKey("approver", false, null)).toBe("wait.person");
    expect(waitKey("you", false, true)).toBe("wait.person");
    expect(waitKey("requester", true, false)).toBe("wait.you");
  });
  it("says an agent is on it only when the server's record shows one at work", () => {
    expect(waitKey("rca_agent", false, true)).toBe("wait.agent");
    expect(waitKey("sre_agent", true, true)).toBe("wait.agent");
    expect(waitKey("rca_agent", false, false)).toBe("wait.agentIdle");     // an open issue nobody has picked up is not «an agent is on it»
    expect(waitKey("sre_agent", false, null)).toBeNull();                   // the record is not loaded: say nothing yet
  });
  it("names the executor, or nobody", () => {
    expect(waitKey("executor", false, null)).toBe("wait.executor");
    expect(waitKey(null, false, null)).toBe("wait.none");
  });
});

describe("storyOrigin — where «经过» was opened from, and so where its way back leads", () => {
  it("takes the lens and the address it was given", () => {
    expect(storyOrigin({ from: "decide", back: "/app/new/decide/I12?f=approval" })).toEqual({ from: "decide", back: "/app/new/decide/I12?f=approval" });
    expect(storyOrigin({ from: "live", back: "/app/new/live" })).toEqual({ from: "live", back: "/app/new/live" });
  });
  it("is nothing for a direct link, and never an address outside NewUI", () => {
    expect(storyOrigin(null)).toBeNull();
    expect(storyOrigin({})).toBeNull();
    expect(storyOrigin({ from: "decide", back: "https://example.org/" })).toBeNull();
    expect(storyOrigin({ from: "decide", back: "//example.org/app/new/decide" })).toBeNull();
    expect(storyOrigin({ from: "decide", back: "/app/issues/12" })).toBeNull();
    expect(storyOrigin({ from: "elsewhere", back: "/app/new/decide" })).toBeNull();
  });
  it("names an item's page", () => {
    expect(storyPath("I12")).toBe("/app/new/story/I12");
  });
});

const plan = (over: Partial<FixPlan> = {}): FixPlan => ({
  id: 7, plan_kind: "fix", status: "pending_approval", steps: [], step_tiers: [], plan_version: 2, content_hash: "0123456789abcdef",
  risk_level: "L1", approved_at: null, ...over,
} as FixPlan);
const run = (over: Partial<FixExecution> = {}): FixExecution => ({
  id: 31, fix_plan_id: 7, status: "succeeded", step_results: [], duration_ms: 65_000, started_at: "2026-11-17T08:00:00", created_at: "2026-11-17T07:59:58",
  ...over,
} as FixExecution);

describe("reachedOf — how far an issue got, from the data there is", () => {
  it("reads a diagnosis, a plan, an approval and a run", () => {
    expect(reachedOf(null, null, [])).toEqual({ rca: false, plan: false, approved: false, run: false });
    expect(reachedOf({}, plan(), [])).toEqual({ rca: true, plan: true, approved: false, run: false });
    expect(reachedOf({}, plan({ status: "approved", approved_at: "2026-11-17T08:00:00" }), [run()])).toEqual({ rca: true, plan: true, approved: true, run: true });
  });
  it("a plan that ran was approved, whatever became of it", () => {
    for (const status of ["executing", "executed", "failed"] as const) expect(reachedOf({}, plan({ status }), undefined).approved).toBe(true);
    expect(reachedOf({}, plan({ status: "rejected" }), undefined).approved).toBe(false);
  });
});

describe("planLine — a plan in one line", () => {
  it("counts the steps and, when the code classified every one, those that change things", () => {
    const p = plan({ steps: [{ action: "a", command: "aws ec2 describe-instances" }, { action: "b", command: "kubectl scale deploy x --replicas=3" },
                             { action: "c", command: "frobnicate" }], step_tiers: ["readonly", "write", "unknown"] });
    expect(planLine(p)).toEqual({ version: 2, hash8: "01234567", steps: 3, writes: 1, unclear: 1 });
  });
  it("claims nothing about the steps when the server sent no classification", () => {
    expect(planLine(plan({ steps: [{ action: "a" }, { action: "b" }], step_tiers: undefined }))).toMatchObject({ steps: 2, writes: null, unclear: 0 });
    expect(planLine(plan({ steps: [{ action: "a" }, { action: "b" }], step_tiers: ["write"] }))).toMatchObject({ steps: 2, writes: null });   // a list of another length
  });
  it("a plan stored before content hashes has none to show", () => {
    expect(planLine(plan({ content_hash: null, plan_version: 0 }))).toMatchObject({ version: 1, hash8: null });
  });
});

describe("runLine — a run in one line", () => {
  it("counts the steps that reported success against the plan it ran", () => {
    const p = plan({ steps: [{ action: "a" }, { action: "b" }, { action: "c" }] });
    const r = run({ step_results: [{ status: "success" }, { status: "failed", error: "boom" }], status: "failed" });
    expect(runLine(r, p)).toEqual({ id: 31, status: "failed", bad: true, done: 1, total: 3, duration: "1m 05s", at: "2026-11-17T08:00:00" });
  });
  it("without its plan, counts against the steps the run reported", () => {
    expect(runLine(run({ step_results: [{ status: "success" }, { status: "success" }] }), null)).toMatchObject({ done: 2, total: 2, bad: false });
  });
  it("a run with no recorded duration or start says so by saying nothing", () => {
    expect(runLine(run({ duration_ms: 0, started_at: null }), null)).toMatchObject({ duration: null, at: "2026-11-17T07:59:58" });
  });
  it("rolled back and aborted are not good ends; in flight is neither", () => {
    expect(runLine(run({ status: "rolled_back" }), null).bad).toBe(true);
    expect(runLine(run({ status: "aborted" }), null).bad).toBe(true);
    expect(runLine(run({ status: "running" }), null).bad).toBe(false);
  });
});

const ev = (id: number, event_type: string, detail: unknown, actor = "user:alice", created_at = `2026-11-17T08:0${id}:00`): PipelineEvent =>
  ({ id, event_type, stage: "issue", status: "completed", detail, actor, duration_ms: null, created_at, trace_id: null } as PipelineEvent);

describe("closure — who dismissed an issue, when, and the reason they gave", () => {
  it("is the newest move to dismissed", () => {
    const events = [
      ev(1, "status_changed", { from: "open", to: "dismissed", reason: "first" }),
      ev(2, "status_changed", { from: "dismissed", to: "open", reason: "reopened" }),
      ev(3, "status_changed", JSON.stringify({ from: "open", to: "dismissed", reason: "known noise from the canary" }), "user:bob"),
    ];
    expect(closure(events)).toEqual({ by: "user:bob", at: "2026-11-17T08:03:00", reason: "known noise from the canary" });
  });
  it("is nothing when the timeline has no such move", () => {
    expect(closure([ev(1, "status_changed", { from: "open", to: "investigating", reason: "x" })])).toBeNull();
    expect(closure(undefined)).toBeNull();
  });
  it("does not quote the server's own filler as a person's reason", () => {
    // PUT /api/issues/{id}/status without a note records the reason «anomaly status update» — nobody wrote that
    expect(closure([ev(1, "status_changed", { from: "open", to: "dismissed", reason: "anomaly status update" })])?.reason).toBe("");
  });
  it("keeps a dismissal that gave no reason", () => {
    expect(closure([ev(1, "status_changed", { from: "open", to: "dismissed" })])).toEqual({ by: "user:alice", at: "2026-11-17T08:01:00", reason: "" });
  });
});

describe("lastMove — who moved the issue to a status last, and when", () => {
  it("finds the newest move to that status, whoever accepted the run before", () => {
    const events = [
      ev(1, "status_changed", { from: "fix_executed", to: "resolved", reason: "first" }, "agent:executor"),
      ev(2, "status_changed", { from: "resolved", to: "open", reason: "regressed" }),
      ev(3, "status_changed", { from: "fix_executed", to: "resolved", reason: "anomaly status update" }, "user:carol"),
    ];
    expect(lastMove(events, "resolved")).toEqual({ by: "user:carol", at: "2026-11-17T08:03:00", reason: "" });
    expect(lastMove(events, "open")?.by).toBe("user:alice");
    expect(lastMove(events, "dismissed")).toBeNull();
  });
});

describe("notesOf — what people wrote on the issue, oldest first", () => {
  it("takes the notes off the timeline, exactly as written", () => {
    const events = [
      ev(3, "note_added", { content: "second\nline two" }, "user:bob"),
      ev(1, "note_added", JSON.stringify({ content: "first" })),
      ev(2, "status_changed", { from: "open", to: "investigating" }),
    ];
    expect(notesOf(events)).toEqual([
      { id: 1, by: "user:alice", at: "2026-11-17T08:01:00", text: "first" },
      { id: 3, by: "user:bob", at: "2026-11-17T08:03:00", text: "second\nline two" },
    ]);
  });
  it("is empty without a timeline", () => {
    expect(notesOf(undefined)).toEqual([]);
  });
});

describe("planBasis — how a plan stands to the diagnosis the page shows", () => {
  const rca = { id: 136, created_at: "2026-09-26T08:04:32" };
  it("says nothing when the plan was written from this diagnosis, after it", () => {
    expect(planBasis({ rca_result_id: 136, created_at: "2026-09-26T08:10:00", updated_at: null }, rca)).toBe("current");
  });
  it("a plan that names another diagnosis was written from an earlier one", () => {
    expect(planBasis({ rca_result_id: 17, created_at: "2026-07-23T08:06:15", updated_at: null }, rca)).toBe("older");
  });
  it("a plan whose record is older than the diagnosis it names was rewritten since — and when is not on record", () => {
    expect(planBasis({ rca_result_id: 136, created_at: "2026-07-23T08:06:15", updated_at: null }, rca)).toBe("rewritten");
    expect(planBasis({ rca_result_id: 136, created_at: "2026-07-23T08:06:15", updated_at: "2026-09-26T08:30:00" }, rca)).toBe("current");   // its last move is on record
  });
  it("claims nothing without a diagnosis, or for a plan that names none", () => {
    expect(planBasis({ rca_result_id: 136, created_at: "2026-07-23T08:06:15", updated_at: null }, null)).toBe("unknown");
    expect(planBasis({ rca_result_id: null, created_at: "2026-07-23T08:06:15", updated_at: null }, rca)).toBe("unknown");
  });
});
