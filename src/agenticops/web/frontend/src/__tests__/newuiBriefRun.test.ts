import { describe, expect, it } from "vitest";
import { executeState, failedVm, resolveVm, runStepsVm, stopOf } from "@/newui/lib/briefs/run";
import type { FixExecution, FixPlan, PostCheckBinding } from "@/api/types";

const bind = (id: string, status: PostCheckBinding["result_status"], problem: PostCheckBinding["problem"] = null): PostCheckBinding =>
  ({ check_id: id, check: `check ${id}`, result_status: status, results: 1, problem });
const run = (over: Partial<FixExecution> = {}): FixExecution => ({
  id: 47, fix_plan_id: 10, health_issue_id: 12, status: "failed", started_at: null, completed_at: null, executed_by: "agent:executor",
  pre_check_results: [], step_results: [], post_check_results: [], rollback_results: [], error_message: null, duration_ms: 65_000,
  verification_status: "failed", verification_reason: null, accepted_by: null, accepted_at: null, acceptance_note: null,
  created_at: "2026-11-17T00:00:00Z", ...over,
});
const plan = (over: Partial<FixPlan> = {}) => ({ id: 10, steps: [{ action: "one", command: "aws a" }, { action: "two", command: "aws b" }, { action: "three", command: "aws c" }],
  step_tiers: ["readonly", "write", "write"], pre_checks: [], post_checks: [{}, {}], rollback_plan: {}, plan_version: 3,
  content_hash: "0123456789abcdef", approved_hash: "0123456789abcdef", ...over } as unknown as FixPlan);

describe("runStepsVm — the plan's steps with what the run reported for each", () => {
  it("marks each step done or failed, and the ones after the failure as never run", () => {
    const steps = runStepsVm(run({ step_results: [{ status: "success", output: "ok" }, { status: "failed", error: "AccessDenied" }] }), plan());
    expect(steps.map((s) => [s.say, s.cmd, s.tier, s.mark, s.output])).toEqual([
      ["one", "aws a", "readonly", "ok", "ok"], ["two", "aws b", "write", "bad", "AccessDenied"], ["three", "aws c", "write", "skip", ""],
    ]);
  });
  it("falls back to what the results say when the run's plan is unknown", () => {
    const steps = runStepsVm(run({ step_results: [{ step: "did a thing", status: "passed" }, { command: "aws b", status: "error", message: "boom" }] }), null);
    expect(steps.map((s) => [s.say, s.mark, s.output])).toEqual([["did a thing", "ok", ""], ["aws b", "bad", "boom"]]);
  });
});

describe("failedVm — why a run ended as a failure", () => {
  it("a step failed: which one, and what the rollback did", () => {
    const vm = failedVm(run({ step_results: [{ status: "success" }, { status: "failed" }], error_message: "step 2 failed",
      rollback_results: [{ status: "success" }, { status: "failed" }] }), plan());
    expect(vm).toMatchObject({ runId: 47, variant: "step", failedAt: 2, duration: "1m 05s", error: "step 2 failed", rollback: { ran: 2, failed: 1 } });
  });
  it("the run succeeded but a declared check failed", () => {
    const vm = failedVm(run({ status: "succeeded", step_results: [{ status: "success" }], post_check_binding: [bind("pc-1", "pass"), bind("pc-2", "fail")] }), plan());
    expect(vm).toMatchObject({ variant: "check", failedAt: null, failedChecks: [{ id: "pc-2", label: "check pc-2" }], rollback: { ran: 0, failed: 0 } });
  });
  it("a person turned the result down at acceptance", () => {
    const vm = failedVm(run({ status: "succeeded", accepted_by: "user:alice", accepted_at: "2026-11-17T01:00:00Z", acceptance_note: "pc-4 still warns" }), plan());
    expect(vm).toMatchObject({ variant: "rejected", by: "user:alice", at: "2026-11-17T01:00:00Z", note: "pc-4 still warns" });
  });
  it("claims no step when none reported a failure", () => {
    expect(failedVm(run({ step_results: [{ status: "success" }] }), plan()).failedAt).toBeNull();
  });
  it("a person stopped it: who, when, what they wrote, and how many steps had been done by then (N9)", () => {
    const vm = failedVm(run({ status: "rolled_back", step_results: [{ status: "success" }], rollback_results: [{ status: "success" }],
      stop_requested_at: "2026-11-17T01:00:00Z", stop_requested_by: "user:alice", stop_note: "wrong change window" }), plan());
    expect(vm.stopped).toEqual({ by: "user:alice", at: "2026-11-17T01:00:00Z", note: "wrong change window", done: 1, reported: 1, late: false });
    expect(vm.rollback).toEqual({ ran: 1, failed: 0 });
  });
  it("a stopped run whose executor recorded nothing: no step is claimed done — none was reported at all", () => {
    const vm = failedVm(run({ status: "failed", step_results: undefined, stop_requested_at: "2026-11-17T01:00:00Z", stop_requested_by: "user:alice" }), plan());
    expect(vm.stopped).toMatchObject({ done: 0, reported: 0, note: null });
  });
  it("a run nobody stopped has no stop to tell", () => {
    expect(failedVm(run({ step_results: [{ status: "failed" }] }), plan()).stopped).toBeNull();
  });
});

describe("stopOf — a person asked the run to stop (N9)", () => {
  it("is nothing when nobody asked", () => {
    expect(stopOf(run({}))).toBeNull();
  });
  it("says who and when; a stop that came after the steps were done was too late — the run ended as a success", () => {
    const asked = { stop_requested_at: "2026-11-17T01:00:00Z", stop_requested_by: "user:alice", stop_note: "" };
    expect(stopOf(run({ status: "rolled_back", ...asked }))).toEqual({ by: "user:alice", at: "2026-11-17T01:00:00Z", note: null, late: false });
    expect(stopOf(run({ status: "succeeded", ...asked }))?.late).toBe(true);
    expect(stopOf(run({ status: "running", ...asked }))?.late).toBe(false);          // still going: not known yet
  });
});

describe("resolveVm — a run that ended, waiting to be closed by a person", () => {
  it("passed: every declared check passed", () => {
    const vm = resolveVm(run({ status: "succeeded", verification_status: "passed", step_results: [{ status: "success" }, { status: "success" }, { status: "success" }],
      post_check_binding: [bind("pc-1", "pass"), bind("pc-2", "pass")] }), plan());
    expect(vm).toMatchObject({ variant: "passed", runId: 47, done: 3, total: 3, version: 3, hash8: "01234567", matchesApproved: true });
    expect(vm.passed).toEqual([{ id: "pc-1", label: "check pc-1" }, { id: "pc-2", label: "check pc-2" }]);
  });
  it("carries a stop a person asked for (N9)", () => {
    expect(resolveVm(run({ status: "succeeded" }), plan()).stop).toBeNull();
    expect(resolveVm(run({ status: "succeeded", stop_requested_at: "2026-11-17T01:00:00Z", stop_requested_by: "user:bob" }), plan()).stop)
      .toMatchObject({ by: "user:bob", late: true });
  });
  it("unverified: the run left no verdict at all", () => {
    expect(resolveVm(run({ status: "succeeded", verification_status: null }), plan()).variant).toBe("unverified");
  });
});

describe("executeState — may this approved plan be run now", () => {
  const act = (over: object) => [{ action: "execute", allowed: true, reason_code: null, effect: "queue_execution", ...over }];
  it("yes when the server allows it", () => {
    expect(executeState(act({}))).toEqual({ can: true, why: null, shadow: false });
    expect(executeState(act({ reason_code: "policy_shadow" }))).toEqual({ can: true, why: null, shadow: true });
  });
  it("no, with the server's reason — the executor switched off is the usual one", () => {
    expect(executeState(act({ allowed: false, reason_code: "executor_disabled" }))).toEqual({ can: false, why: "executor_disabled", shadow: false });
    expect(executeState([])).toEqual({ can: false, why: "state", shadow: false });
    expect(executeState(undefined)).toEqual({ can: false, why: "state", shadow: false });
  });
});
