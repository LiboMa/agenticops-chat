import { describe, expect, it } from "vitest";
import { mergeSteps, nextAfter, planMarks, rollbackHint, runTally, stepVm, type StepRow } from "@/newui/lib/steps";

const row = (id: number, over: Partial<StepRow> = {}): StepRow => ({
  id, kind: "tool", tool: "run_aws_cli", look: "read", tier: "readonly", plan_ref: null, summary: `cmd ${id}`, preview: `out ${id}`,
  outcome: "ok", by: null, started_at: "2026-11-18T03:00:00+00:00", ended_at: "2026-11-18T03:00:02+00:00", delivered_at: null, ...over,
});

describe("stepVm — one recorded step as the page shows it", () => {
  it("a tool that only read is a fact the code fetched: what it returned is the sentence, what it ran is beside it", () => {
    expect(stepVm(row(1))).toMatchObject({ mark: "fact", state: "done", say: "out 1", cmd: "run_aws_cli　cmd 1", tier: "readonly", plan: null });
  });
  it("anything else the agent called is something it did", () => {
    expect(stepVm(row(1, { look: "act", tier: "write", tool: "run_aws_cli" }))).toMatchObject({ mark: "act", tier: "write" });
    expect(stepVm(row(1, { look: "act", tier: null, tool: "save_rca_result" }))).toMatchObject({ mark: "act", tier: null });
  });
  it("a step still running has no result yet", () => {
    expect(stepVm(row(1, { ended_at: null, outcome: null, preview: null }))).toMatchObject({ state: "now", say: "" });
  });
  it("a step that failed, and one that was refused and never ran", () => {
    expect(stepVm(row(1, { outcome: "error", preview: "Error: AccessDenied" }))).toMatchObject({ state: "bad", say: "Error: AccessDenied" });
    expect(stepVm(row(1, { outcome: "refused", preview: "A person stopped this run" }))).toMatchObject({ state: "refused", say: "A person stopped this run" });
  });
  it("what the model said is its own words, with nothing beside it", () => {
    expect(stepVm(row(1, { kind: "say", tool: null, look: null, tier: null, summary: "The timeout is the cause.", preview: null })))
      .toMatchObject({ mark: "say", state: "done", say: "The timeout is the cause.", cmd: null });
  });
  it("a person's note says who wrote it and whether the agent has read it", () => {
    const note = row(1, { kind: "you", tool: null, look: null, tier: null, summary: "check the downstream timeout", preview: null, by: "user:alice", outcome: null, ended_at: null });
    expect(stepVm(note)).toMatchObject({ mark: "you", state: "waiting", by: "user:alice", say: "check the downstream timeout" });
    expect(stepVm({ ...note, delivered_at: "2026-11-18T03:01:00+00:00" })).toMatchObject({ state: "done" });
  });
  it("says where an executor's command stands in its plan", () => {
    expect(stepVm(row(1, { plan_ref: "step:3" })).plan).toEqual({ part: "step", n: 3 });
    expect(stepVm(row(1, { plan_ref: "rollback:1" })).plan).toEqual({ part: "rollback", n: 1 });
    expect(stepVm(row(1, { plan_ref: "post:2" })).plan).toEqual({ part: "post", n: 2 });
    expect(stepVm(row(1, { plan_ref: "off" })).plan).toEqual({ part: "off", n: null });
    expect(stepVm(row(1, { plan_ref: "nonsense" })).plan).toBeNull();
  });
});

describe("mergeSteps / nextAfter — the page fetches only what it does not have", () => {
  it("adds what is new and replaces a step that has ended since", () => {
    const old = [row(1), row(2, { ended_at: null, outcome: null })];
    const merged = mergeSteps(old, [row(2), row(3)]);
    expect(merged.map((s) => [s.id, s.outcome])).toEqual([[1, "ok"], [2, "ok"], [3, "ok"]]);
    expect(mergeSteps(merged, [])).toBe(merged);                          // nothing new: the same list, no re-render
  });
  it("asks again from the first step that has not ended, else from the last one it has", () => {
    expect(nextAfter([])).toBe(0);
    expect(nextAfter([row(4), row(5)])).toBe(5);
    expect(nextAfter([row(4), row(5, { ended_at: null }), row(6)])).toBe(4);
    expect(nextAfter([row(4, { kind: "you", ended_at: null, outcome: null }), row(5)])).toBe(3);   // a note not read yet is asked about again
  });
});

describe("runTally — how an execution's commands stand against its plan", () => {
  it("counts the commands that change something, and how many are word for word a command of the plan", () => {
    const steps = [row(1), row(2, { look: "act", tier: "write", plan_ref: "step:1" }), row(3, { look: "act", tier: "write", plan_ref: "off" }),
                   row(4, { look: "act", tier: "unknown", plan_ref: "off", outcome: "refused" }), row(5, { look: "act", tier: null, tool: "save_execution_result" }),
                   row(6, { kind: "say", look: null, tier: null })];
    expect(runTally(steps)).toEqual({ acts: 3, verbatim: 1, refused: 1 });
  });
  it("is zero for a run that changed nothing", () => {
    expect(runTally([row(1), row(2)])).toEqual({ acts: 0, verbatim: 0, refused: 0 });
  });
});

describe("planMarks — the plan's steps, marked from what was recorded", () => {
  it("marks a step done, running, failed or refused by the command that is word for word its own", () => {
    const steps = [row(1, { plan_ref: "step:1" }), row(2, { plan_ref: "step:2", outcome: "error" }), row(3, { plan_ref: "step:3", outcome: "refused" }),
                   row(4, { plan_ref: "step:4", ended_at: null, outcome: null }), row(5, { plan_ref: "rollback:1" }), row(6, { plan_ref: "off" })];
    expect(planMarks(steps, 5)).toEqual(["done", "bad", "refused", "now", null]);
  });
  it("the newest attempt of a step wins", () => {
    expect(planMarks([row(1, { plan_ref: "step:1", outcome: "error" }), row(2, { plan_ref: "step:1" })], 1)).toEqual(["done"]);
  });
});

describe("rollbackHint — what a stop could roll back, said before the stop", () => {
  it("says when the rollback is not written as commands at all", () => {
    expect(rollbackHint({ steps: 0, commands: 0, as_written: 0 })).toEqual({ key: "stop.rollback.none", n: 0, rest: 0 });
    expect(rollbackHint({ steps: 2, commands: 0, as_written: 0 })).toEqual({ key: "stop.rollback.none", n: 0, rest: 0 });
  });
  it("says when none of its commands can run exactly as written", () => {
    expect(rollbackHint({ steps: 2, commands: 2, as_written: 0 })).toEqual({ key: "stop.rollback.rewrite", n: 2, rest: 0 });
  });
  it("says how many can, and how many cannot", () => {
    expect(rollbackHint({ steps: 3, commands: 3, as_written: 3 })).toEqual({ key: "stop.rollback.all", n: 3, rest: 0 });
    expect(rollbackHint({ steps: 3, commands: 3, as_written: 1 })).toEqual({ key: "stop.rollback.some", n: 1, rest: 2 });
  });
  it("says nothing when the plan is not known", () => {
    expect(rollbackHint(undefined)).toBeNull();
  });
});

// Round-2 review.
describe("stepVm — what a row says once its run is over, and to a read-only account", () => {
  const note = (over: Partial<StepRow>) => row(1, { kind: "you", tool: null, look: null, tier: null, preview: null, outcome: null, ended_at: null,
                                                       summary: "the deploy was rolled back", by: "user:alice", ...over });

  it("a note the run never read says so — it is not «the agent will read it» for ever (B-I3)", () => {
    expect(stepVm(note({ outcome: "missed" as StepRow["outcome"], ended_at: "2026-11-18T03:53:00Z" })).state).toBe("missed");
    expect(stepVm(note({})).state).toBe("waiting");                          // the run is on: it may still be read
    expect(stepVm(note({}), false).state).toBe("missed");                    // an ended run's list: nobody will read it now
    expect(stepVm(note({ delivered_at: "2026-11-18T03:52:30Z" }), false).state).toBe("done");
  });

  it("a step with no recorded end is «running» only while its run is (B-m5)", () => {
    const open = row(1, { tool: "describe_vpcs", ended_at: null, outcome: null, preview: null });
    expect(stepVm(open).state).toBe("now");
    expect(stepVm(open, false).state).toBe("unended");                       // a restart mid-call, or the end was not written
  });

  it("a read-only account is told that a command and its result are not shown — not that there were none (B-I6)", () => {
    const held = stepVm(row(1, { tool: "run_on_host", look: "act", tier: "unknown", summary: "", preview: null, withheld: true }));
    expect([held.withheld, held.cmd, held.say]).toEqual([true, "run_on_host", ""]);
    const read = stepVm(row(1, { tool: "describe_vpcs", tier: null, summary: "region=us-east-1", preview: null, withheld: true }));
    expect([read.withheld, read.cmd]).toEqual([true, "describe_vpcs　region=us-east-1"]);
    expect(stepVm(row(1)).withheld).toBe(false);
  });
});
