import { describe, it, expect } from "vitest";
import { countLabel, reasonKey, safeRoute, tabCounts, type AttentionItem } from "@/lib/attention";

const item = (over: Partial<AttentionItem>) => ({ id: "I1", ref: "I#1", reason: "approval_required", reason_detail: null, title: "t",
  entity: { entity_type: "fix_plan", entity_id: 9, content_version: 2 }, account_id: null, occurred_at: "2026-10-06T10:00:00Z",
  route: "/app/plans/9", available_actions: [], ...over }) as AttentionItem;

describe("Needs your attention (MVP-2.7.0 S3)", () => {
  it("counts to 99+", () => {
    expect([countLabel(0), countLabel(7), countLabel(99), countLabel(100)]).toEqual(["0", "7", "99", "99+"]);
  });
  it("says the detail when known, the reason otherwise, a neutral line for anything new", () => {
    expect(reasonKey(item({ reason: "review_required", reason_detail: "rca_gate" }))).toBe("attention.detail.rca_gate");
    expect(reasonKey(item({ reason: "clarification_required" }))).toBe("attention.reason.clarification_required");
    expect(reasonKey(item({ reason: "something_new", reason_detail: "also_new" }))).toBe("attention.reason.unknown");
  });
  it("only ever navigates inside the app", () => {
    expect(safeRoute("/app/issues/4#accept")).toBe("/app/issues/4#accept");
    expect(safeRoute("/app/plans/9")).toBe("/app/plans/9");
    for (const bad of ["https://evil.example", "//evil.example/app", "/api/settings", "/app/login", "/app/../api", "javascript:alert(1)", null]) {
      expect(safeRoute(bad)).toBeNull();
    }
  });
  it("splits counts per hub tab", () => {
    expect(tabCounts([item({}), item({ id: "C3", entity: { entity_type: "change_request", entity_id: 3, content_version: null } }),
                      item({ id: "I4", entity: { entity_type: "health_issue", entity_id: 4, content_version: null } })])).toEqual({ fix: 1, changes: 1 });
  });
});
