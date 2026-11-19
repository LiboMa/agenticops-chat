import { describe, expect, it } from "vitest";
import type { ChangeRequestListItem, HealthIssue } from "@/api/types";
import { nativeTarget } from "@/lib/shellRoutes";
import { PAGE, changesRequest, issuesRequest, itemRows, itemsQuery, itemsSearch, nextOffset } from "@/newui/lib/items";

const read = (search: string) => itemsQuery(new URLSearchParams(search));

describe("itemsQuery — what the address asks the «all items» table for", () => {
  it("nothing in the address: the issues that are not closed, the newest first", () => {
    expect(read("")).toEqual({ kind: "issue", group: "open", status: null, severity: null, q: "", sort: "newest" });
  });
  it("reads each filter", () => {
    expect(read("?kind=change&st=closed&q=rotate&sort=oldest")).toEqual({ kind: "change", group: "closed", status: null, severity: null, q: "rotate", sort: "oldest" });
    expect(read("?st=all&status=dismissed&sev=critical&sort=severity")).toEqual({ kind: "issue", group: "all", status: "dismissed", severity: "critical", q: "", sort: "severity" });
  });
  it("what it does not know is left out, never passed on", () => {
    expect(read("?kind=plan&st=maybe&status=bogus&sev=urgent&sort=sideways")).toEqual(read(""));
    // a status of the other kind, a severity on changes, a sort changes do not have
    expect(read("?kind=change&status=dismissed&sev=high&sort=severity")).toEqual({ kind: "change", group: "open", status: null, severity: null, q: "", sort: "newest" });
    expect(read("?kind=issue&status=planned").status).toBeNull();
  });
  it("the search text is trimmed and kept to 200 characters, as the server takes it", () => {
    expect(read("?q=%20%20ssh%20").q).toBe("ssh");
    expect(read(`?q=${"x".repeat(300)}`).q).toHaveLength(200);
  });
});

describe("itemsSearch — the address of a choice", () => {
  it("the defaults are not written", () => {
    expect(itemsSearch(read(""))).toBe("");
    expect(itemsSearch({ ...read(""), kind: "change" })).toBe("?kind=change");
  });
  it("round-trips what it writes", () => {
    for (const s of ["?kind=change&st=closed&q=rotate&sort=oldest", "?st=all&status=dismissed&sev=critical&sort=severity", "?q=a%26b%3Dc"]) {
      expect(itemsSearch(read(s))).toBe(s);
      expect(read(itemsSearch(read(s)))).toEqual(read(s));
    }
  });
});

describe("the requests", () => {
  it("issues: the group becomes the statuses the server filters by; the account scope and the page go along", () => {
    expect(issuesRequest(read(""), null, 0)).toBe(
      `/health-issues?status=open%2Cinvestigating%2Cacknowledged%2Croot_cause_identified%2Cfix_planned%2Cfix_approved%2Cfix_executing%2Cfix_executed&sort=newest&limit=${PAGE}&offset=0`);
    expect(issuesRequest(read("?st=closed"), 3, 50)).toBe(`/health-issues?status=resolved%2Cdismissed&sort=newest&account_id=3&limit=${PAGE}&offset=50`);
    expect(issuesRequest(read("?st=all&q=ssh&sev=high&sort=severity"), null, 0)).toBe(`/health-issues?severity=high&q=ssh&sort=severity&limit=${PAGE}&offset=0`);
  });
  it("one exact status wins over its group", () => {
    expect(issuesRequest(read("?st=open&status=dismissed"), null, 0)).toBe(`/health-issues?status=dismissed&sort=newest&limit=${PAGE}&offset=0`);
  });
  it("changes: the same, with their own statuses", () => {
    expect(changesRequest(read("?kind=change"), null, 0)).toBe(
      `/changes?status=draft%2Cunder_review%2Cneeds_clarification%2Cplanned%2Capproved%2Cexecuting%2Cneeds_review&sort=newest&limit=${PAGE}&offset=0`);
    expect(changesRequest(read("?kind=change&st=closed&q=C%233"), 2, 0)).toBe(
      `/changes?status=completed%2Cfailed%2Crolled_back%2Crejected%2Ccancelled&q=C%233&sort=newest&account_id=2&limit=${PAGE}&offset=0`);
    expect(changesRequest(read("?kind=change&st=all&status=planned&sort=oldest"), null, 100)).toBe(`/changes?status=planned&sort=oldest&limit=${PAGE}&offset=100`);
  });
});

describe("nextOffset — whether there is more to load", () => {
  it("the next page starts after what is loaded, until everything is", () => {
    expect(nextOffset(50, 120)).toBe(50);
    expect(nextOffset(100, 120)).toBe(100);
    expect(nextOffset(120, 120)).toBeUndefined();
    expect(nextOffset(0, 0)).toBeUndefined();
  });
  it("a page that came back empty ends it, whatever the total said (rows can go while paging)", () => {
    expect(nextOffset(50, 120, 0)).toBeUndefined();
  });
});

describe("itemRows — a row of the table", () => {
  const issue = (x: Partial<HealthIssue>) => ({ id: 12, title: "SSH open to the world", status: "fix_planned", severity: "high", resource_id: "sg-0abc",
    account_name: "prod", detected_at: "2026-11-18T08:00:00Z", occurrence_count: 1, metric_data: {}, waiting_on: "approver",
    waiting_since: "2026-11-18T09:00:00Z", ...x }) as HealthIssue;
  const change = (x: Record<string, unknown>) => ({ id: 3, title: "Scale out", status: "planned", requested_by: "user:alice", requested_change_type: "normal",
    risk_level: "L2", created_at: "2026-11-17T08:00:00Z", updated_at: "2026-11-18T08:00:00Z", waiting_on: "approver", waiting_since: "2026-11-18T08:00:00Z",
    account_name: "prod", ...x }) as unknown as ChangeRequestListItem;
  it("an issue: its item id, who it waits on as the server said, since when only for a person", () => {
    const [r] = itemRows("issue", [issue({})]);
    expect(r).toMatchObject({ item: "I12", ref: "I#12", title: "SSH open to the world", statusKey: "issues.status.fix_planned", level: "high",
                              waitKey: "workitem.wait.approver", waitSince: "2026-11-18T09:00:00Z", account: "prod", time: "2026-11-18T08:00:00Z", closed: false });
    expect(itemRows("issue", [issue({ status: "investigating", waiting_on: "rca_agent" })])[0]).toMatchObject({ waitKey: "workitem.wait.rca_agent", waitSince: null });
  });
  it("a closed item waits on nobody and is marked closed", () => {
    expect(itemRows("issue", [issue({ status: "resolved", waiting_on: null, waiting_since: null })])[0]).toMatchObject({ waitKey: null, waitSince: null, closed: true });
    expect(itemRows("change", [change({ status: "completed", waiting_on: null })])[0]).toMatchObject({ waitKey: null, closed: true });
  });
  it("a change: C#, its risk level, its last update", () => {
    expect(itemRows("change", [change({})])[0]).toMatchObject({ item: "C3", ref: "C#3", statusKey: "changes.status.planned", level: "L2",
                                                                 waitKey: "workitem.wait.approver", waitSince: "2026-11-18T08:00:00Z", account: "prod", time: "2026-11-18T08:00:00Z" });
  });
  it("keeps the order it was given and drops a row that came twice (a row can move between pages while paging)", () => {
    const rows = itemRows("issue", [issue({ id: 3 }), issue({ id: 2 }), issue({ id: 3 }), issue({ id: 1 })]);
    expect(rows.map((r) => r.item)).toEqual(["I3", "I2", "I1"]);
  });
});

describe("a classic issue-list address lands in the table as the same choice", () => {
  // lib/shellRoutes builds the address (it is part of the entry chunk and may import nothing of NewUI); this is the
  // other side: the table reads back exactly what the classic address meant
  const land = (search: string) => {
    const to = nativeTarget("/app/issues", search, "");
    expect(to).toMatch(/^\/app\/new\/items(\?|$)/);
    return read(to!.split("?")[1] ? `?${to!.split("?")[1]}` : "");
  };
  it("the list of everything keeps its filters", () => {
    expect(land("?view=all")).toEqual(read(""));
    expect(land("?view=all&status=active")).toEqual(read(""));
    expect(land("?view=all&status=all&q=ssh&severity=high&sort=severity")).toEqual({ kind: "issue", group: "all", status: null, severity: "high", q: "ssh", sort: "severity" });
    expect(land("?view=all&status=resolved")).toEqual({ ...read(""), group: "all", status: "resolved" });
    expect(land("?view=all&status=dismissed&sort=oldest")).toEqual({ ...read(""), group: "all", status: "dismissed", sort: "oldest" });
  });
  it("what the table cannot say is dropped (a comma list of severities, the security scope, an unknown value)", () => {
    expect(land("?view=all&severity=critical,high&scope=security&status=whatever")).toEqual(read(""));
  });
});
