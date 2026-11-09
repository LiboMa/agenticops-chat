import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import { acceptReason, canAccept, checklistItems, confirmedIds } from "@/lib/acceptChecklist";
import type { RunSummary } from "@/lib/runSummary";

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
    expect(acceptReason("  looked at the console ", 2, t)).toBe("looked at the console");
    expect(acceptReason("", 2, t)).toBe(t("accept.checklist.reason").replace("{n}", "2"));
    expect(acceptReason("x".repeat(2500), 1, t)).toHaveLength(2000);
  });
});
