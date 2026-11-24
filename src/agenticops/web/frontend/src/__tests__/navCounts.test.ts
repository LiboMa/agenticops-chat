import { describe, expect, it } from "vitest";
import type { NavCounts } from "@/api/types";
import { foldedBadge, navBadge, topBarCount } from "@/lib/navCounts";

/** The sidebar's numbers (MVP-2.8.0 direction A): at most one per entry, only when something waits; red only when
 *  it is urgent; never 0, never shown when it could not be counted, none at all for a viewer. */
const data = (over: Partial<NavCounts> = {}): NavCounts => ({
  read_only: false, attention: { total: 6, critical: 0 }, security_high: 5, schedules_failed: 1, skill_drafts: 2,
  generated_at: "2026-11-10T12:00:00Z", ...over,
});
const ok = (over: Partial<NavCounts> = {}) => ({ status: "success" as const, data: data(over) });

describe("navBadge — one quiet number per entry", () => {
  it("issues: what waits on you, solid; red when one of them is critical", () => {
    expect(navBadge("issues", ok(), false)).toMatchObject({ count: 6, tone: "solid", hint: { key: "nav.hint.issuesWaiting", vars: { n: "6" } } });
    const crit = navBadge("issues", ok({ attention: { total: 6, critical: 1 } }), false);
    expect(crit).toMatchObject({ count: 6, tone: "solidDanger", hint: { key: "nav.hint.issuesWaitingCritical", vars: { n: "6", c: "1" } } });
  });
  it("0 shows no number, only the entry's fixed hint", () => {
    expect(navBadge("issues", ok({ attention: { total: 0, critical: 0 } }), false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.issues" } });
    expect(navBadge("security", ok({ security_high: 0 }), false).count).toBeNull();
  });
  it("security and skills grey, schedules red, plans never", () => {
    expect(navBadge("security", ok(), false)).toMatchObject({ count: 5, tone: "muted" });
    expect(navBadge("schedules", ok(), false)).toMatchObject({ count: 1, tone: "danger" });
    expect(navBadge("skills", ok(), false)).toMatchObject({ count: 2, tone: "muted" });
    expect(navBadge("plans", ok(), false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.plans" } });
    expect(navBadge("reports", ok(), false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.reports" } });
  });
  it("a failed request shows no number — even with stale data — and says so", () => {
    const failed = { status: "error" as const, data: data() };
    expect(navBadge("issues", failed, false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.unavailable" } });
    expect(navBadge("plans", failed, false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.plans" } });
    expect(navBadge("security", ok({ security_high: null }), false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.unavailable" } });
  });
  it("still loading: no number yet, the fixed hint", () => {
    expect(navBadge("issues", { status: "pending" as const }, false)).toEqual({ count: null, tone: null, hint: { key: "nav.hint.issues" } });
  });
  it("a viewer sees no numbers anywhere", () => {
    for (const id of ["issues", "security", "schedules", "skills"]) {
      expect(navBadge(id, ok(), true)).toEqual({ count: null, tone: null, hint: { key: `nav.hint.${id}` } });
    }
  });
});

describe("foldedBadge — a folded group keeps its red number", () => {
  const tools = ["overview", "galaxy", "schedules", "resources", "agent-metrics", "skills"];
  it("only the red ones float up to the heading", () => {
    expect(foldedBadge(tools, ok(), false)).toBe(1);
    expect(foldedBadge(tools, ok({ schedules_failed: 0 }), false)).toBeNull();
    expect(foldedBadge(tools, ok(), true)).toBeNull();
  });
});

describe("topBarCount — the top bar's number is the same number", () => {
  it("the to-do total, nothing when it could not be counted", () => {
    expect(topBarCount(ok())).toBe(6);
    expect(topBarCount({ status: "error" as const, data: data() })).toBeNull();
    expect(topBarCount({ status: "pending" as const })).toBeNull();
    expect(topBarCount(ok({ attention: null }))).toBeNull();
  });
});
