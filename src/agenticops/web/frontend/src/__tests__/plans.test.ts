import { describe, it, expect } from "vitest";
import { auditTabVisible, becameTerminalChange, CHANGE_TERMINAL_STATUSES, changeFilters, fixPlanFilters, isTerminalChange, hubRedirect, hubTab, nextTab, planCounts, planLabel, planRef, planRoute, shortHash, toQuery } from "@/lib/plans";
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
    { plan_kind: "fix" as PlanKind, change_request_id: null, health_issue_id: 3, route: "/app/plans/5", ref: "I#3" },
    { plan_kind: "fix" as PlanKind, change_request_id: null, health_issue_id: null, route: "/app/plans/5", ref: "-" },
  ])("$plan_kind change=$change_request_id issue=$health_issue_id -> $route / $ref", (row) => {
    const fp = { id: 5, plan_kind: row.plan_kind, change_request_id: row.change_request_id, health_issue_id: row.health_issue_id };
    expect(planRoute(fp)).toBe(row.route);
    expect(planRef(fp)).toBe(row.ref);
  });
});

describe("the Plans & changes hub (MVP-2.7.0 S3)", () => {
  it.each([[null, "fix"], ["fix", "fix"], ["changes", "changes"], ["audit", "audit"], ["bogus", "fix"]])(
    "tab %s → %s", (raw, tab) => expect(hubTab(raw)).toBe(tab));
  it("an old /app/changes link keeps its query", () => {
    expect(hubRedirect("changes", "?status=planned&account_id=3")).toBe("/app/plans?tab=changes&status=planned&account_id=3");
    expect(hubRedirect("audit", "")).toBe("/app/plans?tab=audit");
    expect(hubRedirect("audit", "?tab=x&period=7d")).toBe("/app/plans?tab=audit&period=7d");
  });
  it("a fix plan opens its own page; a change plan its change", () => {
    expect(planRoute({ id: 9, plan_kind: "fix", change_request_id: null })).toBe("/app/plans/9");
    expect(planRoute({ id: 9, plan_kind: "change", change_request_id: 3 })).toBe("/app/changes/3");
    expect(planRoute({ id: 9, plan_kind: "change", change_request_id: null })).toBe("/app/plans?tab=changes");
  });
});

describe("planLabel / shortHash", () => {
  // the words come from the locale; the shape mirrors services/plan_content.plan_label
  const t = (k: string) => ({ "plans.fixPlan": "fix plan", "plans.implementationPlan": "implementation plan" })[k] ?? k;
  it.each([
    { plan_kind: "fix" as PlanKind, health_issue_id: 12, change_request_id: null, plan_version: 2, label: "I#12 fix plan v2" },
    { plan_kind: "change" as PlanKind, health_issue_id: null, change_request_id: 3, plan_version: 1, label: "C#3 implementation plan v1" },
    { plan_kind: "fix" as PlanKind, health_issue_id: 4, change_request_id: null, plan_version: 0, label: "I#4 fix plan v1" },
  ])("$label", ({ label, ...fp }) => {
    expect(planLabel(fp, t)).toBe(label);
  });
  it("shortens a content hash to 8 characters; no hash is an em dash", () => {
    expect(shortHash("0123456789abcdef")).toBe("01234567");
    expect(shortHash(null)).toBe("—");
  });
});

describe("planCounts", () => {
  it("counts steps / pre / post checks; rollback = its steps, or 1 for a non-empty plan without a steps list", () => {
    expect(planCounts({ steps: [{}, {}], pre_checks: [{}], post_checks: [{}, {}, {}], rollback_plan: { steps: ["a", "b"] } }))
      .toEqual({ steps: 2, preChecks: 1, postChecks: 3, rollback: 2 });
    expect(planCounts({ steps: [], pre_checks: [], post_checks: [], rollback_plan: { description: "undo" } }).rollback).toBe(1);
    expect(planCounts({ steps: [], pre_checks: [], post_checks: [], rollback_plan: {} }).rollback).toBe(0);
    expect(planCounts({ steps: null as unknown as unknown[], pre_checks: undefined as unknown as unknown[], post_checks: [], rollback_plan: null as unknown as Record<string, unknown> }))
      .toEqual({ steps: 0, preChecks: 0, postChecks: 0, rollback: 0 });
  });
});

describe("fixPlanFilters — the hub's URL", () => {
  it("reads the groups, risk, account and search; drops junk", () => {
    expect(fixPlanFilters(new URLSearchParams("status=awaiting&risk=L2&account=3&q=%20nginx%20"))).toEqual(
      { status: "draft,pending_approval", risk_level: "L2", account_id: 3, q: "nginx" });
    expect(fixPlanFilters(new URLSearchParams("status=bogus&risk=L9&account=-1&q="))).toEqual(
      { status: undefined, risk_level: undefined, account_id: undefined, q: undefined });
  });
});

describe("changeFilters — the Changes tab's URL (final review I2)", () => {
  it("an old /app/changes?status=planned link filters the tab, with the API's own names", () => {
    expect(changeFilters(new URLSearchParams("tab=changes&status=planned&account_id=3&requested_by=user%3Abob&period=30d"))).toEqual(
      { status: "planned", account_id: 3, requested_by: "user:bob", period: "30d" });
  });
  it("drops what the API would refuse", () => {
    expect(changeFilters(new URLSearchParams("status=bogus&account_id=x&period=1y"))).toEqual(
      { status: undefined, account_id: undefined, requested_by: undefined, period: undefined });
  });
});

describe("hub tabs — keyboard and who sees Audit (deferred minors M8 / M9)", () => {
  const ids = ["fix", "changes", "audit"] as const;
  it("arrow keys move and wrap; Home / End jump; other keys do nothing", () => {
    expect(nextTab(ids, "fix", "ArrowRight")).toBe("changes");
    expect(nextTab(ids, "audit", "ArrowRight")).toBe("fix");
    expect(nextTab(ids, "fix", "ArrowLeft")).toBe("audit");
    expect(nextTab(ids, "changes", "Home")).toBe("fix");
    expect(nextTab(ids, "changes", "End")).toBe("audit");
    expect(nextTab(ids, "changes", "a")).toBeNull();
  });
  it("Audit is offered only once bootstrap says so — never flashed while it loads", () => {
    expect(auditTabVisible(undefined)).toBe(false);
    expect(auditTabVisible({ auth_enabled: true, user: { is_admin: false } })).toBe(false);
    expect(auditTabVisible({ auth_enabled: true, user: { is_admin: true } })).toBe(true);
    expect(auditTabVisible({ auth_enabled: false, user: { is_admin: false } })).toBe(true);
  });
});
