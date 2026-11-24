import { describe, expect, it } from "vitest";
import { acceptVm, runToAccept } from "@/newui/lib/briefs/accept";
import type { FixExecution, FixPlan, PostCheckBinding } from "@/api/types";

const bind = (id: string, status: PostCheckBinding["result_status"], problem: PostCheckBinding["problem"] = null): PostCheckBinding =>
  ({ check_id: id, check: `check ${id}`, result_status: status, results: problem === "missing" ? 0 : 1, problem });
const run = (over: Partial<FixExecution> = {}): FixExecution => ({
  id: 47, fix_plan_id: 10, health_issue_id: 12, status: "succeeded", started_at: "2026-11-17T00:00:00Z", completed_at: "2026-11-17T00:02:10Z",
  executed_by: "agent:executor", pre_check_results: [], step_results: [{ status: "success" }, { status: "success" }], post_check_results: [],
  rollback_results: [], error_message: null, duration_ms: 130_000, verification_status: "pending_acceptance",
  verification_reason: "pc-2 has no result", accepted_by: null, accepted_at: null, acceptance_note: null, created_at: "2026-11-17T00:00:00Z", ...over,
});
const plan = { id: 10, steps: [{}, {}], pre_checks: [], post_checks: [{}, {}, {}], rollback_plan: {}, plan_version: 2,
  content_hash: "0123456789abcdef", approved_hash: "0123456789abcdef" } as unknown as FixPlan;

describe("runToAccept — only an issue's latest run can be accepted", () => {
  it("is the newest run when it waits for acceptance", () => {
    expect(runToAccept([run({ id: 48 }), run({ id: 47, verification_status: "passed" })])?.id).toBe(48);
  });
  it("is none when the newest run does not wait — an older pending one cannot be accepted any more", () => {
    expect(runToAccept([run({ id: 48, verification_status: "failed" }), run({ id: 47 })])).toBeNull();
    expect(runToAccept([])).toBeNull();
    expect(runToAccept(undefined)).toBeNull();
  });
});

describe("acceptVm — what ran, what the code checked, what a person must look at", () => {
  const vm = acceptVm(run({ post_check_binding: [bind("pc-1", "pass"), bind("pc-2", "missing", "missing"), bind("pc-3", "warning")] }), plan);

  it("says how the run went, against the run's own plan", () => {
    expect(vm).toMatchObject({ runId: 47, stepsDone: 2, stepsTotal: 2, duration: "2m 10s", planVersion: 2, hash8: "01234567",
      matchesApproved: true, reason: "pc-2 has no result" });
  });

  it("splits the declared checks: passed by code, and the ones still to verify", () => {
    expect(vm.passed).toEqual([{ id: "pc-1", label: "check pc-1" }]);
    expect(vm.toVerify).toEqual([{ id: "pc-2", label: "check pc-2", state: "pending" }, { id: "pc-3", label: "check pc-3", state: "warning" }]);
    expect(vm.failed).toEqual([]);
  });

  it("lists a failed check apart", () => {
    expect(acceptVm(run({ post_check_binding: [bind("pc-1", "fail")] }), plan).failed).toEqual([{ id: "pc-1", label: "check pc-1" }]);
  });

  it("claims nothing about the approval when the run's plan is unknown", () => {
    expect(acceptVm(run({}), null)).toMatchObject({ planVersion: null, hash8: null, matchesApproved: null, stepsTotal: 2 });
  });
  it("says when a person asked the run to stop and it was still recorded as a success (N9)", () => {
    expect(acceptVm(run({}), plan).stop).toBeNull();
    expect(acceptVm(run({ stop_requested_at: "2026-11-17T00:01:00Z", stop_requested_by: "user:alice" }), plan).stop)
      .toEqual({ by: "user:alice", at: "2026-11-17T00:01:00Z", note: null, late: true });
  });
});
