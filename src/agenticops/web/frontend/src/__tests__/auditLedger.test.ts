import { describe, it, expect } from "vitest";
import { ApiError } from "@/api/client";
import {
  decisionKind,
  mergeDecisionRows,
  fillDailySeries,
  fmtSecs,
  fmtRate,
  isForbidden,
  type KindFilter,
} from "@/lib/auditLedger";
import type { AuditLogEntry } from "@/api/types";

/** A full AuditLogEntry with the fields under test overridden. */
function mk(over: Partial<AuditLogEntry> & { id: number }): AuditLogEntry {
  return {
    timestamp: "2026-09-01T00:00:00",
    user_id: null,
    user_email: null,
    actor: null,
    action: "change.approved",
    entity_type: "change_request",
    entity_id: "1",
    entity_name: null,
    details: null,
    old_values: null,
    new_values: null,
    ip_address: null,
    ...over,
  };
}

// A string `details` is off-type but appears on legacy rows (Task 1 R12).
const strDetails = "legacy" as unknown as Record<string, unknown>;

describe("decisionKind", () => {
  it.each<{ name: string; row: Pick<AuditLogEntry, "action" | "entity_type" | "details">; result: "fix" | "change" | null }>([
    { name: "change.* on any entity", row: { action: "change.approved", entity_type: "fix_plan", details: null }, result: "change" },
    { name: "plan.* without change kind", row: { action: "plan.approved", entity_type: "fix_plan", details: {} }, result: "fix" },
    { name: "plan.* echo of a change", row: { action: "plan.approved", entity_type: "fix_plan", details: { plan_kind: "change" } }, result: null },
    { name: "authz.* on change_request", row: { action: "authz.denied", entity_type: "change_request", details: {} }, result: "change" },
    { name: "authz.* on a fix plan", row: { action: "authz.denied", entity_type: "fix_plan", details: {} }, result: "fix" },
    { name: "authz.* on a change's plan", row: { action: "authz.denied", entity_type: "fix_plan", details: { plan_kind: "change" } }, result: "change" },
    { name: "authz.* subject-less, change permission", row: { action: "authz.denied", entity_type: "system", details: { permission: "change.request" } }, result: "change" },
    { name: "authz.* subject-less, plan permission", row: { action: "authz.denied", entity_type: "system", details: { permission: "plan.approve" } }, result: "fix" },
    { name: "authz.* subject-less, other permission", row: { action: "authz.denied", entity_type: "system", details: { permission: "resource.read" } }, result: null },
    { name: "a non-decision action", row: { action: "settings.updated", entity_type: "settings", details: {} }, result: null },
    { name: "plan.* with null details", row: { action: "plan.approved", entity_type: "fix_plan", details: null }, result: "fix" },
    { name: "plan.* with a string details", row: { action: "plan.approved", entity_type: "fix_plan", details: strDetails }, result: "fix" },
    { name: "system denial with change.request permission", row: { action: "authz.denied", entity_type: "system", details: { permission: "change.request" } }, result: "change" },
    { name: "system denial with audit.read permission", row: { action: "authz.denied", entity_type: "system", details: { permission: "audit.read" } }, result: null },
    { name: "settings.updated", row: { action: "settings.updated", entity_type: "chat_session", details: null }, result: null },
  ])("$name -> $result", ({ row, result }) => {
    expect(decisionKind(row)).toBe(result);
  });
});

describe("mergeDecisionRows", () => {
  // t1 < t3 < t4 < t5
  const t1 = "2026-09-01T00:00:00";
  const t3 = "2026-09-03T00:00:00";
  const t4 = "2026-09-04T00:00:00";
  const t5 = "2026-09-05T00:00:00";
  const change = (id: number, timestamp: string) => mk({ id, timestamp, action: "change.approved", entity_type: "change_request" });
  const fix = (id: number, timestamp: string) => mk({ id, timestamp, action: "plan.approved", entity_type: "fix_plan", details: {} });
  const echo = (id: number, timestamp: string) => mk({ id, timestamp, action: "plan.approved", entity_type: "fix_plan", details: { plan_kind: "change" } });

  it("dedupes the same id across two pages", () => {
    const r = change(7, t5);
    const { rows } = mergeDecisionRows([[r], [r]], "all", 100);
    expect(rows.map((x) => x.id)).toEqual([7]);
  });

  it("filters by kind", () => {
    const pages = [[change(20, t5)], [fix(10, t4), echo(30, t3)], undefined];
    expect(mergeDecisionRows(pages, "all", 100).rows.map((r) => r.id)).toEqual([20, 10]);
    expect(mergeDecisionRows(pages, "fix", 100).rows.map((r) => r.id)).toEqual([10]);
    expect(mergeDecisionRows(pages, "change", 100).rows.map((r) => r.id)).toEqual([20]);
  });

  it("drops the change echo under every kind", () => {
    const pages = [[change(20, t5)], [fix(10, t4), echo(30, t3)]];
    for (const k of ["all", "fix", "change"] as KindFilter[]) {
      expect(mergeDecisionRows(pages, k, 100).rows.some((r) => r.id === 30)).toBe(false);
    }
  });

  it("applies the cutoff of the full pages' oldest rows", () => {
    const A = [change(5, t5), change(3, t3)];
    const B = [change(4, t4), change(1, t1)];
    const { rows, truncated } = mergeDecisionRows([A, B], "all", 2);
    expect(rows.map((r) => r.id)).toEqual([5, 4]);
    expect(truncated).toBe(true);
  });

  it("adds no cutoff when no page is full", () => {
    const A = [change(5, t5), change(4, t4)];
    const B = [change(3, t3), change(1, t1)];
    const { rows, truncated } = mergeDecisionRows([A, B], "all", 5);
    expect(rows.map((r) => r.id)).toEqual([5, 4, 3, 1]);
    expect(truncated).toBe(false);
  });

  it("is truncated when the filtered length exceeds the limit", () => {
    const A = [change(5, t5), change(4, t4)];
    const B = [change(3, t3), change(1, t1)];
    const { rows, truncated } = mergeDecisionRows([A, B], "all", 3);
    expect(rows.map((r) => r.id)).toEqual([5, 4, 3]);
    expect(truncated).toBe(true);
  });

  it("breaks a timestamp tie by id descending", () => {
    const rows = mergeDecisionRows([[change(1, t5), change(2, t5)]], "all", 100).rows;
    expect(rows.map((r) => r.id)).toEqual([2, 1]);
  });
});

describe("fillDailySeries", () => {
  const row = (bucket: string, created = 0, completed = 0, failed = 0) => ({ bucket, created, completed, failed });

  it("zero-fills the ends of a three-day period", () => {
    const middle = row("2026-09-02", 5, 4, 1);
    const out = fillDailySeries([middle], "2026-09-01T00:00:00+00:00", "2026-09-03T12:00:00+00:00");
    expect(out.map((r) => r.bucket)).toEqual(["2026-09-01", "2026-09-02", "2026-09-03"]);
    expect(out[0]).toEqual(row("2026-09-01"));
    expect(out[1]).toBe(middle);
    expect(out[2]).toEqual(row("2026-09-03"));
  });

  it("returns one row when start and end are the same day", () => {
    const out = fillDailySeries([], "2026-09-01T01:00:00+00:00", "2026-09-01T23:00:00+00:00");
    expect(out.map((r) => r.bucket)).toEqual(["2026-09-01"]);
  });

  it("keeps a row outside the range, in bucket order", () => {
    const out = fillDailySeries([row("2026-08-15", 1)], "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00");
    expect(out.map((r) => r.bucket)).toEqual(["2026-08-15", "2026-09-01", "2026-09-02"]);
  });

  it("returns the input sorted when a bound is not a date", () => {
    const series = [row("2026-09-02"), row("2026-09-01")];
    const out = fillDailySeries(series, "garbage", "2026-09-03T00:00:00+00:00");
    expect(out.map((r) => r.bucket)).toEqual(["2026-09-01", "2026-09-02"]);
  });
});

describe("fmtSecs", () => {
  it.each([
    [45, "45s"],
    [90, "2m"],
    [5399, "90m"],
    [5400, "1.5h"],
    [7200, "2.0h"],
    [null, "-"],
  ])("%s -> %s", (input, expected) => {
    expect(fmtSecs(input as number | null)).toBe(expected);
  });
});

describe("fmtRate", () => {
  it.each([
    [0.953, "95%"],
    [1, "100%"],
    [0, "0%"],
    [null, "-"],
  ])("%s -> %s", (input, expected) => {
    expect(fmtRate(input as number | null)).toBe(expected);
  });
});

describe("isForbidden", () => {
  it("is true for a 401 or 403 ApiError", () => {
    expect(isForbidden(new ApiError(403, "x"))).toBe(true);
    expect(isForbidden(new ApiError(401, "x"))).toBe(true);
  });
  it("is false for any other error", () => {
    expect(isForbidden(new ApiError(500, "x"))).toBe(false);
    expect(isForbidden(new Error("x"))).toBe(false);
    expect(isForbidden(null)).toBe(false);
  });
});
