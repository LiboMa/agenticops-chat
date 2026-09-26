import { describe, it, expect } from "vitest";
import { becameTerminalChange, CHANGE_TERMINAL_STATUSES, isTerminalChange, planRef, planRoute, resolvePlansTab, toQuery } from "@/lib/plans";
import type { ChangeStatus, PlanKind } from "@/api/types";

describe("toQuery", () => {
  it("drops undefined, null and empty-string values", () => {
    expect(toQuery({ status: "draft", account_id: undefined, requested_by: null, period: "" })).toBe("?status=draft");
  });
  it("keeps 0: a zero offset is a value, not an absent one", () => {
    expect(toQuery({ offset: 0, limit: 50 })).toBe("?offset=0&limit=50");
  });
  it('returns "" when there is nothing to send', () => {
    expect(toQuery({})).toBe("");
  });
});

describe("isTerminalChange", () => {
  it("is true for a terminal status, false for a moving one and for undefined", () => {
    expect(isTerminalChange("rolled_back")).toBe(true);
    expect(isTerminalChange("under_review")).toBe(false);
    expect(isTerminalChange(undefined)).toBe(false);
  });
});

describe("becameTerminalChange (I1)", () => {
  it("is true only on the non-terminal -> terminal flip", () => {
    expect(becameTerminalChange("executing", "completed")).toBe(true);
  });
  it("is false when both ends are the same status", () => {
    expect(becameTerminalChange("completed", "completed")).toBe(false);
    expect(becameTerminalChange("executing", "executing")).toBe(false);
  });
  it("is false when neither end is terminal", () => {
    expect(becameTerminalChange(undefined, "executing")).toBe(false);
  });
  it("is false on a terminal -> terminal move", () => {
    expect(becameTerminalChange("completed", "failed")).toBe(false);
  });
});

describe("terminal sets are typed (M3)", () => {
  it("the constructor rejects a misspelt member at compile time", () => {
    // @ts-expect-error M3: "canceled" (one l) is not a ChangeStatus
    const s = new Set<ChangeStatus>(["canceled"]);
    expect(s).toBeDefined();
  });
  it("the set's element type narrows .has to ChangeStatus", () => {
    // @ts-expect-error M3: CHANGE_TERMINAL_STATUSES is ReadonlySet<ChangeStatus>, not <string>
    CHANGE_TERMINAL_STATUSES.has("definitely-not-a-status");
    expect(CHANGE_TERMINAL_STATUSES.has("completed")).toBe(true);
  });
});

describe("planRoute / planRef (R2)", () => {
  it.each([
    { plan_kind: "change" as PlanKind, change_request_id: 7, health_issue_id: null, route: "/app/changes/7", ref: "C#7" },
    { plan_kind: "change" as PlanKind, change_request_id: null, health_issue_id: null, route: "/app/plans?tab=changes", ref: "-" },
    { plan_kind: "fix" as PlanKind, change_request_id: null, health_issue_id: 3, route: "/app/issues/3", ref: "I#3" },
    { plan_kind: "fix" as PlanKind, change_request_id: null, health_issue_id: null, route: "/app/plans?tab=fix", ref: "-" },
  ])("$plan_kind change=$change_request_id issue=$health_issue_id -> $route / $ref", (row) => {
    const fp = { plan_kind: row.plan_kind, change_request_id: row.change_request_id, health_issue_id: row.health_issue_id };
    expect(planRoute(fp)).toBe(row.route);
    expect(planRef(fp)).toBe(row.ref);
  });
});

describe("resolvePlansTab", () => {
  it.each([
    { requested: null, changesOn: true, result: "changes" },
    { requested: null, changesOn: false, result: "fix" },
    { requested: "changes", changesOn: false, result: "fix" },
    { requested: "audit", changesOn: false, result: "audit" },
    { requested: "fix", changesOn: true, result: "fix" },
    { requested: "bogus", changesOn: true, result: "changes" },
  ])("$requested with changesOn=$changesOn -> $result", ({ requested, changesOn, result }) => {
    expect(resolvePlansTab(requested, changesOn)).toBe(result);
  });
});
