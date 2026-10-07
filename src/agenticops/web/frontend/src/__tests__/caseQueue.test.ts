import { describe, it, expect } from "vitest";
import {
  ACTIVE_STATUSES, QUEUE_CAP, backTarget, capped, caseHref, queueFilters, queueParams, rowState, scrollKey, SPLIT_MIN_WIDTH,
} from "@/lib/caseQueue";

const q = (s: string) => queueFilters(new URLSearchParams(s));

describe("queueFilters: the URL → GET /api/health-issues (MVP-2.7.0 S4)", () => {
  it("defaults: ops events, newest first, one more than the cap so the view knows it was capped", () => {
    expect(q("")).toEqual({ scope: "ops", sort: "newest", limit: QUEUE_CAP + 1 });
    expect(QUEUE_CAP).toBe(200);
  });
  it("status groups map onto the API's status lists", () => {
    expect(q("status=active").status).toBe(ACTIVE_STATUSES.join(","));
    expect(ACTIVE_STATUSES).not.toContain("resolved");
    expect(ACTIVE_STATUSES).not.toContain("dismissed");
    expect(ACTIVE_STATUSES).toHaveLength(8);
    expect(q("status=resolved").status).toBe("resolved");
    expect(q("status=dismissed").status).toBe("dismissed");
    expect(q("status=all").status).toBeUndefined();
    expect(q("status=bogus").status).toBeUndefined();
  });
  it("scope, severity, search and sort are kept when valid, dropped when not", () => {
    expect(q("scope=security&severity=critical&q=%20nginx%20&sort=severity"))
      .toEqual({ scope: "security", severity: "critical", q: "nginx", sort: "severity", limit: 201 });
    expect(q("scope=x&severity=hgh&q=%20%20&sort=random")).toEqual({ scope: "ops", sort: "newest", limit: 201 });
    expect(q(`q=${"a".repeat(250)}`).q).toHaveLength(200);
  });
});

describe("queue URL helpers", () => {
  it("a case link keeps the queue's query and never a hash", () => {
    expect(caseHref(12, "?status=active")).toBe("/app/issues/12?status=active");
    expect(caseHref(12, "")).toBe("/app/issues/12");
  });
  it("the same filters in another order share one scroll key", () => {
    expect(scrollKey("?b=2&a=1")).toBe(scrollKey("?a=1&b=2"));
    expect(scrollKey("?a=1")).not.toBe(scrollKey("?a=2"));
    expect(scrollKey("").startsWith("aiops-cases-scroll:")).toBe(true);
  });
  it("back goes through history when the case was opened from the queue, else to the list with the same query", () => {
    expect(backTarget({ fromQueue: true }, "?status=active")).toEqual({ kind: "history" });
    expect(backTarget(null, "?status=active")).toEqual({ kind: "link", to: "/app/issues?status=active" });
    expect(backTarget({ other: 1 }, "")).toEqual({ kind: "link", to: "/app/issues" });
  });
  it("201 rows mean capped: the view shows 200 and says so", () => {
    expect(capped(new Array(201).fill(0))).toBe(true);
    expect(capped(new Array(200).fill(0))).toBe(false);
  });
  it("queueParams writes one filter and drops a default, so the URL stays short", () => {
    expect(queueParams(new URLSearchParams("scope=all"), "status", "active").toString()).toBe("scope=all&status=active");
    expect(queueParams(new URLSearchParams("status=active"), "status", "").toString()).toBe("");
    expect(queueParams(new URLSearchParams("scope=all"), "scope", "ops").toString()).toBe("");
    expect(queueParams(new URLSearchParams("sort=oldest"), "sort", "newest").toString()).toBe("");
  });
  it("the split view starts at 1280px", () => {
    expect(SPLIT_MIN_WIDTH).toBe(1280);
  });
});

describe("rowState (review I1)", () => {
  it("only a narrow screen marks the navigation as from the queue — split-view selections never become a 'back' target", () => {
    expect(rowState(false)).toEqual({ fromQueue: true });
    expect(rowState(true)).toBeUndefined();
  });
});
