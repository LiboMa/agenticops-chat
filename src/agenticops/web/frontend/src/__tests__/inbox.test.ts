import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import {
  INBOX_TABS, inboxParams, inboxSearch, nextTab, parseItem, selectionState, tabCount, tabReasons, waitFact, waitLabel,
} from "@/lib/inbox";

const tEn = (k: string) => (en as Record<string, string>)[k] ?? k;
const tZh = (k: string) => (zh as Record<string, string>)[k] ?? k;
const NOW = Date.parse("2026-11-09T12:00:00Z");

describe("the workbench's decision tabs (MVP-2.8.0 S2)", () => {
  it("map onto the attention reasons; not started joins failed, clarification joins to-confirm", () => {
    expect(INBOX_TABS).toEqual(["all", "approval", "acceptance", "failed", "confirm"]);
    expect(tabReasons("all")).toBeNull();
    expect(tabReasons("approval")).toEqual(["approval_required"]);
    expect(tabReasons("acceptance")).toEqual(["verification_required"]);
    expect(tabReasons("failed")).toEqual(["execution_failed", "execution_not_started"]);
    expect(tabReasons("confirm")).toEqual(["review_required", "clarification_required"]);
  });
  it("count from the server's per-reason counts", () => {
    const counts = { approval_required: 2, execution_failed: 1, execution_not_started: 3, review_required: 4 };
    expect(tabCount(counts, "all")).toBe(10);
    expect(tabCount(counts, "failed")).toBe(4);
    expect(tabCount(counts, "acceptance")).toBe(0);
    expect(tabCount(undefined, "all")).toBe(0);
  });
});

describe("inboxParams / inboxSearch — the workbench's state lives in the URL", () => {
  it("round-trips and drops defaults; `decision`, never `tab` (the issue page's legacy param)", () => {
    const p = inboxParams("?decision=acceptance&q=%20disk%20&item=I12&layout=compact");
    expect(p).toEqual({ decision: "acceptance", q: "disk", item: "I12", layout: "compact" });
    expect(inboxSearch(p)).toBe("?decision=acceptance&q=disk&item=I12&layout=compact");
    expect(inboxSearch(inboxParams(""))).toBe("");
    expect(inboxSearch({ ...inboxParams(""), item: "C3" })).toBe("?item=C3");
  });
  it("falls back to defaults on unknown values and caps the search", () => {
    expect(inboxParams("?decision=everything&layout=wide&item=X9")).toEqual(
      { decision: "all", q: "", item: null, layout: "split" });
    expect(inboxParams(`?q=${"x".repeat(300)}`).q).toHaveLength(200);
  });
});

describe("parseItem", () => {
  it("reads an issue or a change ref; anything else is null", () => {
    expect(parseItem("I12")).toEqual({ kind: "issue", id: 12 });
    expect(parseItem("C3")).toEqual({ kind: "change", id: 3 });
    for (const bad of [null, "", "I", "I0", "I-1", "X3", "I12a", "c3"]) expect(parseItem(bad)).toBeNull();
  });
});

describe("waitLabel — how long it has waited", () => {
  it("says minutes, hours, days", () => {
    expect(waitLabel("2026-11-09T11:59:40Z", NOW, tEn)).toBe("Just now");
    expect(waitLabel("2026-11-09T11:35:00Z", NOW, tEn)).toBe("Waiting 25 min");
    expect(waitLabel("2026-11-09T09:00:00Z", NOW, tEn)).toBe("Waiting 3 h");
    expect(waitLabel("2026-11-06T12:00:00Z", NOW, tEn)).toBe("Waiting 3 days");
    expect(waitLabel("2026-11-09T11:35:00Z", NOW, tZh)).toBe("已等 25 分钟");
    expect(waitLabel("2026-11-09T09:00:00", NOW, tZh)).toBe("已等 3 小时");   // a naive API time is UTC
  });
  it("is null for nothing or a time in the future", () => {
    expect(waitLabel(null, NOW, tEn)).toBeNull();
    expect(waitLabel("2026-11-09T13:00:00Z", NOW, tEn)).toBe("Just now");
  });
});

describe("selectionState — the selected item may just have been handled", () => {
  const items = [{ id: "I1" }, { id: "C2" }];
  it("selected / gone / none", () => {
    expect(selectionState(items, "C2")).toBe("selected");
    expect(selectionState(items, "I9")).toBe("gone");
    expect(selectionState(items, null)).toBe("none");
  });
});

describe("waitFact — a duration only while a person is waited on (E2E C#2; S2 review)", () => {
  it("nobody waits (a completed change): no duration, never «已等 40 天»", () => {
    expect(waitFact(null, "2026-10-01T00:00:00Z", NOW, tZh)).toBeNull();
  });
  it("a system works (the executor, the SRE agent): no duration — a running fix never reads «等执行器 · 已等 2 天»", () => {
    expect(waitFact("executor", "2026-11-07T12:00:00Z", NOW, tZh)).toBeNull();
    expect(waitFact("sre_agent", "2026-11-07T12:00:00Z", NOW, tZh)).toBeNull();
  });
  it("a person (you, an approver, the requester, an acceptor): the duration since it started waiting", () => {
    for (const who of ["you", "approver", "requester", "acceptor"]) {
      expect(waitFact(who, "2026-11-09T09:00:00Z", NOW, tEn)).toBe(waitLabel("2026-11-09T09:00:00Z", NOW, tEn));
    }
  });
});

describe("selectionState with what the page knows (S2 review)", () => {
  it("the list has not loaded, or it failed: the item is shown — never «already handled»", () => {
    expect(selectionState([], "I12", { ready: false })).toBe("selected");
  });
  it("an item seen in this view that has left it is gone, even while more pages could be loaded", () => {
    expect(selectionState([{ id: "I2" }], "I1", { ready: true, hasMore: true, seen: new Set(["I1", "I2"]) })).toBe("gone");
  });
  it("a deep link not seen yet while more pages exist may sit on a later page: shown", () => {
    expect(selectionState([{ id: "I2" }], "I9", { ready: true, hasMore: true, seen: new Set(["I2"]) })).toBe("selected");
  });
  it("everything loaded and it is not there: gone", () => {
    expect(selectionState([{ id: "I2" }], "I9", { ready: true, hasMore: false })).toBe("gone");
  });
});

describe("the decision tabs take the keyboard (S2 leftover)", () => {
  it("arrows move and wrap, Home / End go to the ends, any other key is not ours", () => {
    expect(nextTab(INBOX_TABS, "all", "ArrowRight")).toBe("approval");
    expect(nextTab(INBOX_TABS, "confirm", "ArrowRight")).toBe("all");
    expect(nextTab(INBOX_TABS, "all", "ArrowLeft")).toBe("confirm");
    expect(nextTab(INBOX_TABS, "failed", "ArrowLeft")).toBe("acceptance");
    expect(nextTab(INBOX_TABS, "failed", "Home")).toBe("all");
    expect(nextTab(INBOX_TABS, "approval", "End")).toBe("confirm");
    expect(nextTab(INBOX_TABS, "all", "Enter")).toBeNull();
    expect(nextTab(INBOX_TABS, "all", "ArrowDown")).toBeNull();
  });
});
