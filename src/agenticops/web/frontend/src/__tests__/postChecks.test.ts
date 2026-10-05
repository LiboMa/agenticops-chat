import { describe, it, expect } from "vitest";
import { postCheckRows } from "@/lib/postChecks";
import type { FixExecution, PostCheckBinding } from "@/api/types";

const run = (post: unknown[], binding: PostCheckBinding[]): FixExecution => ({
  id: 1, fix_plan_id: 1, health_issue_id: 1, status: "succeeded", started_at: null, completed_at: null,
  executed_by: "executor_agent", pre_check_results: [], step_results: [], post_check_results: post,
  rollback_results: [], error_message: null, duration_ms: 0, verification_status: "pending_acceptance",
  verification_reason: null, accepted_by: null, accepted_at: null, acceptance_note: null, created_at: "",
  post_check_binding: binding,
});

const row = (check_id: string | null, check: string | null, result_status: PostCheckBinding["result_status"],
             results: number, problem: PostCheckBinding["problem"]): PostCheckBinding =>
  ({ check_id, check, result_status, results, problem });

describe("postCheckRows", () => {
  it("pairs each declared check with the result that names it, output included", () => {
    const ex = run(
      [{ check_id: "pc-2", status: "passed", output: "200 OK" }, { check_id: "pc-1", status: "passed", output: "ready" }],
      [row("pc-1", "rollout ready", "pass", 1, null), row("pc-2", "http health", "pass", 1, null)],
    );
    const { legacy, rows } = postCheckRows(ex);
    expect(legacy).toBe(false);
    expect(rows.map((r) => [r.label, r.title, r.outcome, r.problem, r.output])).toEqual([
      ["pc-1", "rollout ready", "pass", null, "ready"],
      ["pc-2", "http health", "pass", null, "200 OK"],
    ]);
  });

  it("shows the September counterexample as a duplicate and a missing check", () => {
    const ex = run(
      [{ check_id: "pc-1", status: "passed" }, { check_id: "pc-1", status: "passed" }],
      [row("pc-1", "rollout ready", "pass", 2, "duplicate"), row("pc-2", "http health", null, 0, "missing")],
    );
    expect(postCheckRows(ex).rows.map((r) => [r.label, r.problem, r.count, r.outcome])).toEqual([
      ["pc-1", "duplicate", 2, "pass"],
      ["pc-2", "missing", 0, null],
    ]);
  });

  it("lists stray results after the declared checks, with their own output", () => {
    const ex = run(
      [{ check_id: "pc-1", status: "passed" }, { check_id: "pc-9", status: "passed", output: "x" },
       { check: "free text", status: "failed", output: "y" }],
      [row("pc-1", "a", "pass", 1, null), row("pc-9", null, "pass", 1, "undeclared"), row(null, null, "fail", 1, "unbound")],
    );
    expect(postCheckRows(ex).rows.slice(1).map((r) => [r.label, r.title, r.problem, r.output])).toEqual([
      ["pc-9", "", "undeclared", "x"],
      ["—", "free text", "unbound", "y"],
    ]);
  });

  it("reads a run recorded before binding (no result has a check_id) as legacy, in reported order", () => {
    const ex = run([{ check: "healthy", status: "passed" }], [row("pc-1", "healthy", null, 0, "missing"), row(null, null, "pass", 1, "unbound")]);
    expect(postCheckRows(ex).legacy).toBe(true);
  });

  it("is not legacy when nothing was reported: every declared check shows as missing", () => {
    const ex = run([], [row("pc-1", "a", null, 0, "missing")]);
    const { legacy, rows } = postCheckRows(ex);
    expect(legacy).toBe(false);
    expect(rows.map((r) => r.problem)).toEqual(["missing"]);
  });

  it("falls back to legacy when the server sent no binding", () => {
    expect(postCheckRows(run([{ status: "passed" }], [])).legacy).toBe(true);
  });
});
