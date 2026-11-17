import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { groupOf } from "@/lib/inbox";
import {
  FILTERS, currentItem, deepLinkState, emptyKind, flattenPages, groupCounts, parseFilter, pruneHandled, reasonsParam, situation, step,
  toneOf, waitedParts, withoutHandled,
} from "@/newui/lib/queue";
import type { AttentionItem } from "@/lib/attention";

const shared = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/attention_decision_groups.json"), "utf8")) as
  { groups: string[]; reasons: Record<string, string> };
const item = (id: string, over: Partial<AttentionItem> = {}): AttentionItem => ({
  id, ref: id.replace(/^([IC])/, "$1#"), reason: "approval_required", reason_detail: null, title: id,
  entity: { entity_type: id.startsWith("C") ? "change_request" : "fix_plan", entity_id: 1, content_version: 1 },
  account_id: 1, occurred_at: "2026-11-17T00:00:00Z", route: "/app/plans/1", available_actions: [], ...over,
});

describe("the queue's filters are the server's decision groups", () => {
  it("offers «all» and exactly the shared groups", () => {
    expect([...FILTERS].sort()).toEqual(["all", ...shared.groups].sort());
  });

  it("asks the server for exactly the reasons of a group, in a stable order", () => {
    expect(reasonsParam("all")).toBeNull();
    for (const g of shared.groups) {
      const want = Object.keys(shared.reasons).filter((r) => shared.reasons[r] === g).sort().join(",");
      expect(reasonsParam(g as (typeof FILTERS)[number])).toBe(want);
      for (const r of want.split(",")) expect(groupOf(r)).toBe(g);
    }
  });

  it("reads an unknown or missing filter as «all»", () => {
    expect(parseFilter("approval")).toBe("approval");
    for (const bad of [null, undefined, "", "nope", "ALL"]) expect(parseFilter(bad)).toBe("all");
  });
});

describe("groupCounts — numbers the server counted, never a guess", () => {
  it("adds the reasons of each group and the total", () => {
    expect(groupCounts({ approval_required: 108, verification_required: 2, review_required: 18, execution_not_started: 12 }))
      .toEqual({ all: 140, approval: 108, acceptance: 2, confirm: 18, failed: 12 });
    expect(groupCounts({})).toEqual({ all: 0, approval: 0, acceptance: 0, confirm: 0, failed: 0 });
  });

  it("is null when the counts did not arrive — the page then shows «—», not 0", () => {
    expect(groupCounts(undefined)).toBeNull();
    expect(groupCounts(null)).toBeNull();
  });

  it("counts a reason this client does not know in the total only", () => {
    expect(groupCounts({ approval_required: 1, something_new: 4 })).toEqual({ all: 5, approval: 1, acceptance: 0, confirm: 0, failed: 0 });
  });
});

describe("flattenPages", () => {
  it("keeps the server's order and drops an item a later page repeats", () => {
    const pages = [{ items: [item("I1"), item("I2")] }, { items: [item("I2"), item("C3")] }];
    expect(flattenPages(pages).map((i) => i.id)).toEqual(["I1", "I2", "C3"]);
    expect(flattenPages(undefined)).toEqual([]);
  });
});

describe("currentItem — the selection survives a reorder", () => {
  const items = [item("I1"), item("I2"), item("C3")];
  it("is the item with the selected id, wherever it now sits", () => {
    expect(currentItem(items, "C3", 0)).toEqual({ item: items[2], index: 2 });
    expect(currentItem([items[2], items[0], items[1]], "I1", 0)?.index).toBe(1);
  });
  it("falls to the same place in the list when the selected item has left, and to the last when the list is shorter", () => {
    expect(currentItem(items, "I9", 1)?.item.id).toBe("I2");
    expect(currentItem(items, "I9", 7)?.item.id).toBe("C3");
    expect(currentItem(items, null, 0)?.item.id).toBe("I1");
  });
  it("is null for an empty list", () => {
    expect(currentItem([], "I1", 0)).toBeNull();
  });
});

describe("step", () => {
  it("moves and wraps at both ends", () => {
    expect(step(3, 0, 1)).toBe(1);
    expect(step(3, 2, 1)).toBe(0);
    expect(step(3, 0, -1)).toBe(2);
    expect(step(0, 0, 1)).toBe(0);
  });
});

describe("emptyKind — why the list is empty", () => {
  const none = { all: 0, approval: 0, acceptance: 0, confirm: 0, failed: 0 };
  it("a read-only account is never handed anything: that is not «all done»", () => {
    expect(emptyKind({ filter: "all", counts: none, readOnly: true })).toBe("readOnly");
  });
  it("a filter with nothing in it, while other things wait", () => {
    expect(emptyKind({ filter: "acceptance", counts: { ...none, all: 4, approval: 4 }, readOnly: false })).toBe("filtered");
  });
  it("nothing waits at all", () => {
    expect(emptyKind({ filter: "all", counts: none, readOnly: false })).toBe("clear");
    expect(emptyKind({ filter: "approval", counts: none, readOnly: false })).toBe("clear");
    expect(emptyKind({ filter: "approval", counts: null, readOnly: false })).toBe("clear");
  });
});

describe("toneOf — the bar at the row's left edge", () => {
  it("follows an issue's severity", () => {
    expect(toneOf(item("I1", { severity: "critical" }))).toBe("crit");
    expect(toneOf(item("I1", { severity: "high" }))).toBe("warn");
    expect(toneOf(item("I1", { severity: "medium" }))).toBe("warn");
    expect(toneOf(item("I1", { severity: "low" }))).toBe("info");
  });
  it("follows a change's risk level", () => {
    expect(toneOf(item("C1", { risk_level: "L3" }))).toBe("crit");
    expect(toneOf(item("C1", { risk_level: "L2" }))).toBe("warn");
    expect(toneOf(item("C1", { risk_level: "L1" }))).toBe("info");
  });
  it("is plain when neither is known", () => {
    expect(toneOf(item("I1"))).toBe("");
    expect(toneOf(item("I1", { severity: "odd" }))).toBe("");
  });
});

describe("waitedParts — how long it has waited (as the classic page: whole units, rounded down)", () => {
  const NOW = Date.parse("2026-11-17T12:00:00Z");
  it("minutes, hours, days", () => {
    expect(waitedParts("2026-11-17T11:35:00Z", NOW)).toEqual({ unit: "min", n: 25 });
    expect(waitedParts("2026-11-17T09:01:00Z", NOW)).toEqual({ unit: "hour", n: 2 });
    expect(waitedParts("2026-11-14T12:00:00Z", NOW)).toEqual({ unit: "day", n: 3 });
    expect(waitedParts("2026-11-17T09:00:00", NOW)).toEqual({ unit: "hour", n: 3 });   // a naive API time is UTC
  });
  it("under a minute, or a clock ahead of ours, is «just now»", () => {
    expect(waitedParts("2026-11-17T11:59:40Z", NOW)).toEqual({ unit: "now", n: 0 });
    expect(waitedParts("2026-11-17T13:00:00Z", NOW)).toEqual({ unit: "now", n: 0 });
  });
  it("is null without a time", () => {
    expect(waitedParts(null, NOW)).toBeNull();
    expect(waitedParts("not a date", NOW)).toBeNull();
  });
});

describe("deepLinkState — an address that names an item", () => {
  const items = [{ id: "I1" }, { id: "C2" }];
  it("found, or nothing asked", () => {
    expect(deepLinkState({ item: "C2", items, ready: true, hasMore: false })).toBe("found");
    expect(deepLinkState({ item: null, items, ready: true, hasMore: false })).toBe("none");
  });
  it("may still sit on a page not loaded yet", () => {
    expect(deepLinkState({ item: "I9", items, ready: true, hasMore: true })).toBe("loading");
    expect(deepLinkState({ item: "I9", items: [], ready: false, hasMore: false })).toBe("loading");
  });
  it("is not waiting on you once every page is in and it is not there", () => {
    expect(deepLinkState({ item: "I9", items, ready: true, hasMore: false })).toBe("gone");
  });
});

describe("handled items — what was just decided leaves the list at once, without waiting for the next refresh", () => {
  const approval = item("I10");
  const notStarted = item("I10", { reason: "execution_not_started" });
  const handled = new Map([["I10", situation(approval)]]);

  it("drops an item decided a moment ago while the server still lists it as it was", () => {
    expect(withoutHandled([item("I1"), approval, item("C3")], handled).map((i) => i.id)).toEqual(["I1", "C3"]);
    expect(withoutHandled([approval], new Map())).toEqual([approval]);
  });

  it("shows it again as soon as it is another situation — approved, then «did not start»", () => {
    expect(withoutHandled([notStarted], handled)).toEqual([notStarted]);
  });

  it("tells situations apart by reason, detail, the entity and its version", () => {
    const base = situation(approval);
    expect(situation(item("I10", { reason_detail: "x" }))).not.toBe(base);
    expect(situation(item("I10", { entity: { entity_type: "fix_plan", entity_id: 2, content_version: 1 } }))).not.toBe(base);
    expect(situation(item("I10", { entity: { entity_type: "fix_plan", entity_id: 1, content_version: 2 } }))).not.toBe(base);
    expect(situation(item("I10", { title: "another title", occurred_at: "2026-01-01T00:00:00Z" }))).toBe(base);
  });

  it("forgets a mark once the list no longer has the item as it was", () => {
    expect([...pruneHandled([approval], handled)]).toEqual([["I10", situation(approval)]]);    // still listed as it was: keep
    expect(pruneHandled([notStarted], handled).size).toBe(0);                                  // came back changed
    expect(pruneHandled([item("I1")], handled).size).toBe(0);                                  // gone
    expect(pruneHandled([approval], handled)).toBe(handled);                                   // nothing to forget: the same map
  });
});
