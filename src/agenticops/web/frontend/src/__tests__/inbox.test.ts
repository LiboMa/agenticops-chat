import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DECISION_GROUPS, groupItems, groupOf, parseItem, selectionState, waitFact, waitLabel } from "@/lib/inbox";
import type { AttentionItem } from "@/lib/attention";

const tEn = (k: string) => (en as Record<string, string>)[k] ?? k;
const tZh = (k: string) => (zh as Record<string, string>)[k] ?? k;
const NOW = Date.parse("2026-11-09T12:00:00Z");

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

describe("«在等我» groups the to-do items by the decision they need (MVP-2.8.0)", () => {
  const shared = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/attention_decision_groups.json"), "utf8"));
  const it_ = (id: string, reason: string) => ({ id, reason } as unknown as AttentionItem);
  it("the same groups as the server (services/attention.DECISION_OF)", () => {
    expect(DECISION_GROUPS).toEqual(shared.groups);
    for (const [reason, group] of Object.entries(shared.reasons)) expect(groupOf(reason)).toBe(group);
  });
  it("groups in the fixed order, counts include rows not loaded yet, an empty group is left out", () => {
    const items = [it_("I1", "approval_required"), it_("C2", "approval_required"), it_("I3", "execution_not_started"),
                   it_("C4", "clarification_required")];
    const counts = { approval_required: 5, execution_not_started: 1, execution_failed: 2, clarification_required: 1, review_required: 3 };
    const g = groupItems(items, counts);
    expect(g.map((x) => [x.group, x.count, x.items.map((i) => i.id)])).toEqual([
      ["approval", 5, ["I1", "C2"]], ["failed", 3, ["I3"]], ["confirm", 4, ["C4"]],
    ]);
  });
});

