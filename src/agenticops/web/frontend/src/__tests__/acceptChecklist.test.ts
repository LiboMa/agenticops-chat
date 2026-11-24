import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import { acceptReason, canAccept, checklistItems, confirmedIds } from "@/lib/acceptChecklist";
import { runSummary, type RunSummary } from "@/lib/runSummary";
import type { FixExecution, FixPlan } from "@/api/types";

const t = (k: string) => (en as Record<string, string>)[k] ?? k;
const summary = (checks: RunSummary["checks"]): RunSummary =>
  ({ stepsDone: 1, stepsTotal: 1, planId: 1, version: 1, hash8: "abcd1234", matchesApproved: true, checks, warnings: [] });

describe("the acceptance checklist (MVP-2.8.0 S2)", () => {
  it("one box per check still to verify (no result, or a warning), then one overall confirmation", () => {
    const items = checklistItems(summary([
      { id: "pc-1", label: "sg ok", state: "passed" },
      { id: "pc-2", label: "ssh source", state: "pending" },
      { id: "pc-3", label: "latency", state: "warning" },
    ]), t);
    expect(items.map((i) => i.id)).toEqual(["pc-2", "pc-3", null]);
    expect(items[0].label).toContain("ssh source");
    expect(items[2].label).toBe(t("accept.checklist.overall"));
  });
  it("no declared checks: only the overall confirmation", () => {
    expect(checklistItems(summary([]), t).map((i) => i.id)).toEqual([null]);
  });
  it("sends only the declared ids ticked; confirm needs every box", () => {
    const items = checklistItems(summary([{ id: "pc-2", label: "x", state: "pending" }]), t);
    expect(canAccept(items, new Set([0]))).toBe(false);
    expect(canAccept(items, new Set([0, 1]))).toBe(true);
    expect(confirmedIds(items, new Set([0, 1]))).toEqual(["pc-2"]);
    expect(confirmedIds(items, new Set([1]))).toEqual([]);
  });
  it("a note is the reason; without one the reason says what was checked (the API needs 1–2000 chars)", () => {
    const two = checklistItems(summary([
      { id: "pc-1", label: "a", state: "pending" }, { id: "pc-2", label: "b", state: "warning" },
    ]), t);
    expect(acceptReason("  looked at the console ", two, t)).toBe("looked at the console");
    expect(acceptReason("x".repeat(2500), two, t)).toHaveLength(2000);
    // the count is the checks, never the overall confirmation after them (S2 leftover: two checks read «3»)
    expect(acceptReason("", two, t)).toBe(t("accept.checklist.reason").replace("{n}", "2"));
    // no check to verify: no «0 items», the overall confirmation in words
    expect(acceptReason("", checklistItems(summary([]), t), t)).toBe(t("accept.checklist.reasonOverall"));
  });
});

describe("the checklist never sends an id the server refuses (S2 review)", () => {
  it("a stray result for pc-4 on a one-check plan: only the overall box, no pc-4", () => {
    const summary = runSummary({
      id: 7, fix_plan_id: 1, status: "succeeded", step_results: [{ status: "succeeded" }],
      post_check_results: [{ check_id: "pc-1", status: "passed" }, { check_id: "pc-4", status: "passed" }],
      post_check_binding: [
        { check_id: "pc-1", check: "sg ok", result_status: "pass", results: 1, problem: null },
        { check_id: "pc-4", check: null, result_status: "pass", results: 1, problem: "undeclared" },
      ],
    } as unknown as FixExecution, { id: 1, steps: [{}], post_checks: [{ check: "sg ok" }], content_hash: "a",
                                    approved_hash: "a", plan_version: 1 } as unknown as FixPlan);
    const items = checklistItems(summary, t);
    expect(items.map((i) => i.id)).toEqual([null]);
    expect(confirmedIds(items, new Set([0]))).toEqual([]);
  });
});
