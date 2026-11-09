import { describe, expect, it } from "vitest";
import type { FixExecution, FixPlan } from "@/api/types";
import { runSummary } from "@/lib/runSummary";

const plan = (over: Partial<FixPlan> = {}): FixPlan => ({
  id: 225, plan_kind: "fix", plan_version: 1, content_hash: "5a5e2e1c99", approved_hash: "5a5e2e1c99",
  steps: Array.from({ length: 8 }, (_, i) => ({ command: `step ${i}` })), post_checks: [{ check: "sg ok" }],
  pre_checks: [], rollback_plan: {}, ...over,
} as unknown as FixPlan);

const run = (over: Partial<FixExecution> = {}): FixExecution => ({
  id: 7, fix_plan_id: 225, status: "succeeded",
  step_results: Array.from({ length: 8 }, () => ({ status: "succeeded" })),
  post_check_results: [{ check_id: "pc-1", status: "passed" }],
  post_check_binding: [{ check_id: "pc-1", check: "sg ok", result_status: "pass", results: 1, problem: null }],
  ...over,
} as unknown as FixExecution);

describe("runSummary — the first screen's latest-run block (MVP-2.8.0 S2)", () => {
  it("counts the steps done against the run's plan, binds the version and hash, lists each check", () => {
    const s = runSummary(run(), plan());
    expect(s).toMatchObject({ stepsDone: 8, stepsTotal: 8, planId: 225, version: 1, hash8: "5a5e2e1c", matchesApproved: true });
    expect(s.checks).toEqual([{ id: "pc-1", label: "sg ok", state: "passed" }]);
    expect(s.warnings).toEqual([]);
  });

  it("uses the run's own plan, not the current one (a run of an older plan)", () => {
    const old = plan({ id: 200, plan_version: 3, steps: [{ command: "a" }, { command: "b" }] });
    const s = runSummary(run({ fix_plan_id: 200, step_results: [{ status: "succeeded" }] }), old);
    expect(s).toMatchObject({ stepsDone: 1, stepsTotal: 2, planId: 200, version: 3 });
  });

  it("a check without a result is pending («待核对»), a warning is listed", () => {
    const s = runSummary(run({
      post_check_results: [{ check_id: "pc-2", status: "warning", check: "ssh source" }],
      post_check_binding: [
        { check_id: "pc-1", check: "sg ok", result_status: null, results: 0, problem: "missing" },
        { check_id: "pc-2", check: "ssh source", result_status: "warning", results: 1, problem: null },
      ],
    }), plan({ post_checks: [{ check: "sg ok" }, { check: "ssh source" }] }));
    expect(s.checks).toEqual([
      { id: "pc-1", label: "sg ok", state: "pending" },
      { id: "pc-2", label: "ssh source", state: "warning" },
    ]);
    expect(s.warnings).toEqual(["ssh source"]);
  });

  it("content changed after approval: does not match", () => {
    expect(runSummary(run(), plan({ content_hash: "ffffffff00" })).matchesApproved).toBe(false);
  });

  it("no post-checks: no check lines; no plan: the steps come from the run alone", () => {
    expect(runSummary(run({ post_check_results: [], post_check_binding: [] }), plan({ post_checks: [] })).checks).toEqual([]);
    const s = runSummary(run(), null);
    expect(s).toMatchObject({ stepsDone: 8, stepsTotal: 8, planId: null, version: null, hash8: null, matchesApproved: null });
  });
});
