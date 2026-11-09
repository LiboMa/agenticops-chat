import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import {
  INBOX_TABS, inboxParams, inboxSearch, parseItem, selectionState, tabCount, tabReasons, waitLabel,
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
