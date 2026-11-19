import { describe, it, expect } from "vitest";
import { healthKey, healthView, lifecycleKey, resourceFilters, resourceHref, resourceParams, scanLine } from "@/lib/resourceTable";

const f = (s: string) => resourceFilters(new URLSearchParams(s));

describe("resourceFilters: the URL → GET /api/resources (MVP-2.7.0 S4)", () => {
  it("defaults: page 1 of 50, present resources only", () => {
    expect(f("")).toEqual({ limit: 50, offset: 0, includeAbsent: false, page: 1, size: 50 });
  });
  it("reads type, region, search, absent, page and size; junk falls back", () => {
    expect(f("type=EC2&region=us-east-1&q=%20web%20&absent=1&page=3&size=100"))
      .toEqual({ type: "EC2", region: "us-east-1", search: "web", includeAbsent: true, limit: 100, offset: 200, page: 3, size: 100 });
    expect(f("size=7&page=-2&absent=yes")).toEqual({ limit: 50, offset: 0, includeAbsent: false, page: 1, size: 50 });
    expect(f("page=abc").page).toBe(1);
  });
  it("a filter change goes back to page 1; defaults leave the URL", () => {
    expect(resourceParams(new URLSearchParams("page=4&type=EC2"), "region", "us-east-1").toString()).toBe("type=EC2&region=us-east-1");
    expect(resourceParams(new URLSearchParams("type=EC2"), "type", "").toString()).toBe("");
    expect(resourceParams(new URLSearchParams("size=100"), "size", "50").toString()).toBe("");
    expect(resourceParams(new URLSearchParams("type=EC2"), "page", "2").toString()).toBe("type=EC2&page=2");
    expect(resourceParams(new URLSearchParams("page=2"), "page", "1").toString()).toBe("");
  });
});

describe("resource rows", () => {
  it("health is never 'healthy': no open issue reads unknown, as does a value we do not know", () => {
    expect(healthKey("unknown")).toBe("resources.health.unknown");
    expect(healthKey("notice")).toBe("resources.health.notice");
    expect(healthKey("warning")).toBe("resources.health.warning");
    expect(healthKey("critical")).toBe("resources.health.critical");
    expect(healthKey(null)).toBe("resources.health.unknown");
    expect(healthKey(undefined)).toBe("resources.health.unknown");
    expect(healthKey("healthy")).toBe("resources.health.unknown");
  });
  it("lifecycle: present unless the latest complete scan no longer saw it", () => {
    expect(lifecycleKey({ absent_since: null })).toBe("resources.lifecycle.present");
    expect(lifecycleKey({})).toBe("resources.lifecycle.present");
    expect(lifecycleKey({ absent_since: "2026-10-06T10:00:00" })).toBe("resources.lifecycle.absent");
  });
  it("a row links by its integer key only", () => {
    expect(resourceHref(9)).toBe("/app/resources/9");
  });
});

// ── MVP-2.9.0 N24 (the 2.8.0 spec's S7): every «unknown» has a reason ─────────────────────────────────────────

const NOW = Date.parse("2026-11-19T12:00:00Z");
const row = (o: Record<string, unknown> = {}) => ({ health: "unknown", health_reason: "no_open_issue", open_issues: 0, observed_at: "2026-11-19T11:50:00Z", ...o }) as never;

describe("what the health cell says", () => {
  it("no open issue is «no known issue» — never «healthy», never a bare «unknown»", () => {
    expect(healthView(row(), NOW)).toEqual({ key: "resources.reason.no_open_issue", tone: "neutral", ago: null, issues: 0 });
  });
  it("an open issue says how bad, and how many", () => {
    expect(healthView(row({ health: "critical", health_reason: "open_issue", open_issues: 2 }), NOW))
      .toEqual({ key: "resources.health.critical", tone: "danger", ago: null, issues: 2 });
    expect(healthView(row({ health: "warning", health_reason: "open_issue", open_issues: 1 }), NOW).tone).toBe("warn");
    expect(healthView(row({ health: "notice", health_reason: "open_issue", open_issues: 1 }), NOW).tone).toBe("info");
  });
  it("stale data is recognisable: it says when the row was last observed", () => {
    expect(healthView(row({ health_reason: "stale", observed_at: "2026-11-17T11:00:00Z" }), NOW))
      .toEqual({ key: "resources.reason.stale", tone: "warn", ago: { key: "chat.ago.days", n: 2 }, issues: 0 });
  });
  it("never observed and gone are their own words", () => {
    expect(healthView(row({ health_reason: "never_observed", observed_at: null }), NOW))
      .toEqual({ key: "resources.reason.never_observed", tone: "warn", ago: null, issues: 0 });
    expect(healthView(row({ health_reason: "absent" }), NOW))
      .toEqual({ key: "resources.reason.absent", tone: "neutral", ago: null, issues: 0 });
  });
  it("a row without a reason (an older server) is read from its health alone", () => {
    expect(healthView(row({ health_reason: undefined }), NOW).key).toBe("resources.reason.no_open_issue");
    expect(healthView(row({ health_reason: undefined, health: "warning", open_issues: 3 }), NOW)).toMatchObject({ key: "resources.health.warning", issues: 3 });
    expect(healthView(row({ health_reason: "something new" }), NOW).key).toBe("resources.reason.no_open_issue");
  });
});

describe("«last resource scan»", () => {
  const sched = (o: Record<string, unknown>) => ({ id: 1, pipeline_name: "ResourceScan", is_enabled: true, last_execution: null, ...o }) as never;
  const ran = (status: string, started: string, completed: string | null = null) => ({ id: 9, status, started_at: started, completed_at: completed });
  it("says nothing until the schedules are known", () => {
    expect(scanLine(undefined)).toBeNull();
  });
  it("no resource-scan schedule at all is said as that", () => {
    expect(scanLine([sched({ pipeline_name: "DailyReport" })])).toEqual({ scheduleId: null });
  });
  it("a schedule that never ran", () => {
    expect(scanLine([sched({ id: 4 })])).toEqual({ scheduleId: 4, run: { kind: "never_run" }, at: null, enabled: true });
  });
  it("the newest run among the resource-scan schedules, with its real state and when it ended", () => {
    const line = scanLine([
      sched({ id: 4, last_execution: ran("completed", "2026-11-19T08:00:00Z", "2026-11-19T08:03:00Z") }),
      sched({ id: 7, is_enabled: false, last_execution: ran("failed", "2026-11-19T10:00:00Z", "2026-11-19T10:01:00Z") }),
      sched({ id: 8, pipeline_name: "K8sDiscovery", last_execution: ran("completed", "2026-11-19T11:00:00Z") }),
    ]);
    expect(line).toEqual({ scheduleId: 7, run: { kind: "failed" }, at: "2026-11-19T10:01:00Z", enabled: false });
  });
  it("a run in flight has no end yet: its start is the time", () => {
    expect(scanLine([sched({ id: 4, last_execution: ran("running", "2026-11-19T11:58:00Z") })]))
      .toEqual({ scheduleId: 4, run: { kind: "running" }, at: "2026-11-19T11:58:00Z", enabled: true });
  });
});
