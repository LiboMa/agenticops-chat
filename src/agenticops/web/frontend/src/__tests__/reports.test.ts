import { describe, expect, it } from "vitest";
import {
  REPORTS_PAGE, countsView, coverageView, nextOffset, reportsQuery, reportsRequest, reportsSearch,
} from "@/lib/reports";
import { renderMarkdown, type Heading } from "@/lib/renderMarkdown";
import type { ReportCoverage } from "@/api/types";

describe("the reports list's query lives in the address", () => {
  it("defaults to everything", () => {
    expect(reportsQuery(new URLSearchParams(""))).toEqual({ q: "", from: "", to: "" });
  });
  it("reads a search and two UTC days; a day that is not a day is no filter", () => {
    expect(reportsQuery(new URLSearchParams("q=nginx&from=2026-11-01&to=2026-11-07"))).toEqual({ q: "nginx", from: "2026-11-01", to: "2026-11-07" });
    expect(reportsQuery(new URLSearchParams("from=yesterday&to=2026-13-40&q=" + "x".repeat(300)))).toEqual({ q: "x".repeat(200), from: "", to: "" });
  });
  it("writes back only what is set, and keeps the other parameters", () => {
    expect(reportsSearch(new URLSearchParams("tab=x&q=old"), { q: " nginx ", from: "", to: "2026-11-07" })).toBe("tab=x&q=nginx&to=2026-11-07");
    expect(reportsSearch(new URLSearchParams("q=old&from=2026-11-01"), { q: "", from: "", to: "" })).toBe("");
  });
  it("asks the server for one page of exactly that", () => {
    expect(reportsRequest({ q: "", from: "", to: "" }, 0)).toBe(`/reports?limit=${REPORTS_PAGE}&offset=0`);
    expect(reportsRequest({ q: "100%", from: "2026-11-01", to: "2026-11-07" }, 50))
      .toBe(`/reports?limit=${REPORTS_PAGE}&offset=50&q=100%25&date_from=2026-11-01&date_to=2026-11-07`);
  });
  it("knows when there is more to list", () => {
    expect(nextOffset(50, 128)).toBe(50);
    expect(nextOffset(128, 128)).toBeUndefined();
    expect(nextOffset(0, 0)).toBeUndefined();
    expect(nextOffset(50, 128, 0)).toBeUndefined();      // an empty page: stop, whatever the total says
  });
});

describe("«matched X» and «Z in all» are two numbers", () => {
  it("says only the whole count when nothing is filtered", () => {
    expect(countsView({ q: "", from: "", to: "" }, 128, 128)).toEqual({ matched: null, all: 128 });
  });
  it("says both when a search or a date is set — also when they happen to be equal", () => {
    expect(countsView({ q: "nginx", from: "", to: "" }, 3, 128)).toEqual({ matched: 3, all: 128 });
    expect(countsView({ q: "", from: "2026-01-01", to: "" }, 128, 128)).toEqual({ matched: 128, all: 128 });
  });
});

describe("the coverage card says what the record holds", () => {
  const cov = (o: Partial<ReportCoverage> = {}): ReportCoverage => ({
    accounts: ["lab", "prod"], regions: ["us-east-1"], completeness: "complete",
    partial: { truncated: 0, offloaded: 0, failed: 0 }, read_at: "2026-11-07T09:03:00Z", ...o,
  });
  it("complete: accounts, regions, when it was read", () => {
    expect(coverageView(cov())).toEqual({
      tone: "ok", stateKey: "reports.coverage.complete",
      accounts: ["lab", "prod"], regions: ["us-east-1"], readAt: "2026-11-07T09:03:00Z", partial: [],
    });
  });
  it("partial: each kind of gap with its count, only the ones that happened", () => {
    const v = coverageView(cov({ completeness: "partial", partial: { truncated: 2, offloaded: 0, failed: 1 } }));
    expect(v?.tone).toBe("warn");
    expect(v?.stateKey).toBe("reports.coverage.partial");
    expect(v?.partial).toEqual([{ key: "reports.coverage.truncated", n: 2 }, { key: "reports.coverage.failed", n: 1 }]);
  });
  it("counts decide, not the word: a record with a gap is partial whatever it calls itself", () => {
    expect(coverageView(cov({ completeness: "complete", partial: { truncated: 0, offloaded: 3, failed: 0 } }))?.stateKey).toBe("reports.coverage.partial");
  });
  it("no card for a report without a record, or with one it cannot read", () => {
    expect(coverageView(null)).toBeNull();
    expect(coverageView(undefined)).toBeNull();
    expect(coverageView({ accounts: "prod" } as unknown as ReportCoverage)).toBeNull();
  });
});

describe("the outline comes from the rendering itself", () => {
  const md = ["# Daily report", "", "## Summary", "text", "", "### 未解决的问题", "", "```", "## not a heading", "```", "",
              "## Summary", "", "## **Bold** and `code` [link](https://x.y)", "", "#### too deep", "", "## !!!"].join("\n");
  const headings: Heading[] = [];
  const html = renderMarkdown(md, { headings });

  it("lists h2 and h3 in order, as plain text", () => {
    expect(headings.map((h) => [h.level, h.text])).toEqual([
      [2, "Summary"], [3, "未解决的问题"], [2, "Summary"], [2, "Bold and code link"], [2, "!!!"],
    ]);
  });
  it("gives each a stable id — Chinese stays, a repeat gets a number, an empty one a name", () => {
    expect(headings.map((h) => h.id)).toEqual(["h-summary", "h-未解决的问题", "h-summary-2", "h-bold-and-code-link", "h-section"]);
  });
  it("writes the same ids onto the headings it renders, and onto nothing else", () => {
    for (const h of headings) expect(html).toContain(`<h${h.level} class="md-h${h.level}" id="${h.id}">`);
    expect(html).toContain('<h1 class="md-h1">Daily report</h1>');
    expect(html).toContain('<h4 class="md-h4">too deep</h4>');
    expect(html).not.toContain('id="h-not-a-heading"');
  });
  it("is the same every time, and adds no ids when no outline is asked for", () => {
    const again: Heading[] = [];
    expect(renderMarkdown(md, { headings: again })).toBe(html);
    expect(again).toEqual(headings);
    expect(renderMarkdown(md)).not.toContain(" id=");
  });
});
