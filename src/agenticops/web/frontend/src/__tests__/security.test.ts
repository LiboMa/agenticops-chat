import { describe, expect, it } from "vitest";
import {
  FINDINGS_PAGE, cardView, findingsQuery, findingsRequest, findingsSearch, pageInfo, radarAccount, radarRows,
  scoreTier, trendChart, trendDays,
  exposureView, pathsEmptyKey, pageToShow,
} from "@/lib/security";
import type { SecurityAccountScore, SecurityTrend } from "@/api/types";

const account = (o: Partial<SecurityAccountScore> = {}): SecurityAccountScore => ({
  account_id: 1, account_name: "acct-a", partition: "aws", overall_score: 75, category_scores: { iam: 66.6, network: 100 },
  created_at: "2026-11-19T03:00:00Z", reachable_paths: 1, open_findings: 4, collection: "complete", collection_errors: [], ...o,
});

describe("the score's tier (≥ 80 good, 50–80 watch, < 50 check first)", () => {
  it.each([[100, "good"], [80, "good"], [79.9, "watch"], [50, "watch"], [49.9, "priority"], [0, "priority"]] as const)(
    "%s → %s", (score, tier) => expect(scoreTier(score)).toBe(tier));
});

describe("an account's card", () => {
  it("a scored account: the number, one decimal, and its tier", () => {
    expect(cardView(account())).toEqual({ state: "scored", score: "75.0", tier: "watch", errors: [] });
    expect(cardView(account({ collection: null })).state).toBe("scored");     // written before health was recorded
  });
  it("partly read: still scored, and says so with what failed", () => {
    const errors = [{ source: "iam", error: "AccessDenied (GetCredentialReport)" }];
    expect(cardView(account({ overall_score: 62.5, collection: "partial", collection_errors: errors })))
      .toEqual({ state: "partial", score: "62.5", tier: "watch", errors });
  });
  it("nobody could read it: no number and no tier — never 0, never 100", () => {
    const errors = [{ source: "iam", error: "Timeout" }];
    expect(cardView(account({ overall_score: null, collection: "failed", collection_errors: errors })))
      .toEqual({ state: "unscored", score: null, tier: null, errors });
  });
});

describe("the trend as chart rows", () => {
  const trend: SecurityTrend = { days: 7, accounts: [
    { account_id: 1, account_name: "acct-a", points: [{ day: "2026-11-13", score: 40, partial: true }, { day: "2026-11-19", score: 75, partial: false }] },
    { account_id: 2, account_name: "acct-cn", points: [{ day: "2026-11-18", score: 90, partial: false }] },
    { account_id: 3, account_name: "empty", points: [] },
  ] };
  const chart = trendChart(trend, "2026-11-19");

  it("has every UTC day of the window, so a day without a score is a gap, not a joined line", () => {
    expect(chart.rows.map((r) => r.day)).toEqual(["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]);
    expect(chart.rows.map((r) => r.a0)).toEqual([40, null, null, null, null, null, 75]);
    expect(chart.rows.map((r) => r.a1)).toEqual([null, null, null, null, null, 90, null]);
  });
  it("one line per account; the second and later are dashed, each its own way", () => {
    expect(chart.series).toEqual([
      { key: "a0", name: "acct-a", dash: undefined, points: 2 },
      { key: "a1", name: "acct-cn", dash: "6 4", points: 1 },
      { key: "a2", name: "empty", dash: "2 4", points: 0 },
    ]);
  });
  it("knows which points came from a partly read account", () => {
    expect(chart.partial).toEqual({ "2026-11-13": ["acct-a"] });
  });
  it("a point outside the window is not drawn", () => {
    const old = trendChart({ days: 7, accounts: [{ account_id: 1, account_name: "a", points: [{ day: "2026-11-01", score: 5, partial: false }] }] }, "2026-11-19");
    expect(old.rows.every((r) => r.a0 === null)).toBe(true);
    expect(old.series[0].points).toBe(0);
  });
  it("reads the range from the address: 7, 30 or 90, else 30", () => {
    expect(trendDays(new URLSearchParams("days=7"))).toBe(7);
    expect(trendDays(new URLSearchParams("days=90"))).toBe(90);
    expect(trendDays(new URLSearchParams("days=14"))).toBe(30);
    expect(trendDays(new URLSearchParams(""))).toBe(30);
  });
});

describe("the radar's account", () => {
  const list = [account(), account({ account_id: 2, account_name: "acct-cn" }), account({ account_id: null, account_name: "gone" })];
  it("under one account in the top bar it is that account, whatever was picked", () => {
    expect(radarAccount(list, 2, "acct-a")?.account_name).toBe("acct-cn");
    expect(radarAccount(list, 9, "acct-a")).toBeNull();        // the scoped account has no snapshot: nothing to draw
  });
  it("under «all» it is the one picked on the page, else the first", () => {
    expect(radarAccount(list, null, "gone")?.account_name).toBe("gone");
    expect(radarAccount(list, null, "nobody")?.account_name).toBe("acct-a");
    expect(radarAccount(list, null, null)?.account_name).toBe("acct-a");
    expect(radarAccount([], null, null)).toBeNull();
  });
  it("a category nobody could read is drawn at the centre and marked, not given a number", () => {
    expect(radarRows(account({ category_scores: { network: 100, iam: null, data: 50 } }))).toEqual([
      { category: "data", score: 50, collected: true },
      { category: "iam", score: 0, collected: false },
      { category: "network", score: 100, collected: true },
    ]);
  });
});

describe("the findings list's filters live in the address", () => {
  it("defaults: open, everything else unfiltered, page 1", () => {
    expect(findingsQuery(new URLSearchParams(""))).toEqual({ severity: "", status: "open", reach: "", q: "", page: 1 });
  });
  it("reads what it knows and ignores what it does not", () => {
    expect(findingsQuery(new URLSearchParams("sev=high&st=all&reach=undetermined&q=ssh&p=3")))
      .toEqual({ severity: "high", status: "all", reach: "undetermined", q: "ssh", page: 3 });
    expect(findingsQuery(new URLSearchParams("sev=urgent&st=closed&reach=maybe&p=-2&q=" + "x".repeat(300))))
      .toEqual({ severity: "", status: "open", reach: "", q: "x".repeat(200), page: 1 });
    expect(findingsQuery(new URLSearchParams("p=1.5")).page).toBe(1);
  });
  it("writes back only what differs from the default, and keeps the page's other parameters", () => {
    const now = new URLSearchParams("days=7&sev=high&p=4");
    expect(findingsSearch(now, { severity: "critical", status: "open", reach: "", q: "", page: 1 })).toBe("days=7&sev=critical");
    expect(findingsSearch(now, { severity: "", status: "all", reach: "reachable", q: "a b", page: 2 })).toBe("days=7&st=all&reach=reachable&q=a+b&p=2");
    expect(findingsSearch(new URLSearchParams("sev=high"), { severity: "", status: "open", reach: "", q: "", page: 1 })).toBe("");
  });
  it("asks the server for exactly that page, in the account of the top bar", () => {
    expect(findingsRequest({ severity: "", status: "open", reach: "", q: "", page: 1 }, undefined))
      .toBe(`/security/findings?status=open&limit=${FINDINGS_PAGE}&offset=0`);
    expect(findingsRequest({ severity: "high", status: "all", reach: "reachable", q: "100%", page: 3 }, 2))
      .toBe(`/security/findings?status=all&limit=${FINDINGS_PAGE}&offset=${2 * FINDINGS_PAGE}&account_id=2&severity=high&reachability=reachable&q=100%25`);
  });
  it("says which rows are on screen", () => {
    expect(pageInfo(0, 1)).toEqual({ from: 0, to: 0, page: 1, pages: 1 });
    expect(pageInfo(45, 1)).toEqual({ from: 1, to: 20, page: 1, pages: 3 });
    expect(pageInfo(45, 3)).toEqual({ from: 41, to: 45, page: 3, pages: 3 });
    expect(pageInfo(45, 9)).toEqual({ from: 41, to: 45, page: 3, pages: 3 });      // a page past the end is the last one
  });
});

describe("reachable paths of an account whose security groups were not read (MVP-2.9.0 N27, review)", () => {
  it("is not «0»: nothing was seen and nothing can be said", () => {
    expect(exposureView({ reachable_paths: null, exposure_read: false })).toEqual({ kind: "unread", n: null });
  });
  it("what was seen before the read failed is «at least»", () => {
    expect(exposureView({ reachable_paths: 2, exposure_read: false })).toEqual({ kind: "atLeast", n: 2 });
  });
  it("a read account says its number, zero included; so does a snapshot from before this was recorded", () => {
    expect(exposureView({ reachable_paths: 0, exposure_read: true })).toEqual({ kind: "count", n: 0 });
    expect(exposureView({ reachable_paths: 3, exposure_read: true })).toEqual({ kind: "count", n: 3 });
    expect(exposureView({ reachable_paths: 0, exposure_read: null })).toEqual({ kind: "count", n: 0 });
    expect(exposureView({ reachable_paths: 0 })).toEqual({ kind: "count", n: 0 });
  });
  it("an empty list of paths says «none» only when every account shown was read", () => {
    expect(pathsEmptyKey([{ exposure_read: true }, { exposure_read: null }])).toBe("security.noPaths");
    expect(pathsEmptyKey([{ exposure_read: true }, { exposure_read: false }])).toBe("security.noPaths.unread");
    expect(pathsEmptyKey(undefined)).toBe("security.noPaths");
  });
});

describe("a page past the end of the findings (MVP-2.9.0 N27, review)", () => {
  it("is the last page: «no findings» is not said under a card that counts 59", () => {
    expect(pageToShow(5, 59, 20)).toBe(3);
    expect(pageToShow(4, 60, 20)).toBe(3);
    expect(pageToShow(2, 20, 20)).toBe(1);
  });
  it("a page that exists is itself, and an empty list is page 1", () => {
    expect(pageToShow(3, 59, 20)).toBe(3);
    expect(pageToShow(1, 59, 20)).toBe(1);
    expect(pageToShow(7, 0, 20)).toBe(1);
  });
});
