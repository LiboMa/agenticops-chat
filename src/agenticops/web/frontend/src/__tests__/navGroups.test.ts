import { describe, it, expect } from "vitest";
import { NAV_GROUPS, V1_DEFAULT, defaultOrder, entryForPath, migrateNavOrder, moveWithinGroup, normalizeOrder } from "@/lib/navGroups";

describe("NAV_GROUPS — the blue/white sidebar", () => {
  it("daily work, operations tools, administration; every old entry kept, Settings joins administration", () => {
    expect(NAV_GROUPS.map((g) => [g.id, g.items.map((i) => i.id)])).toEqual([
      ["daily", ["chat", "issues", "reports"]],
      ["tools", ["changes", "audit", "resources", "schedules"]],
      ["administration", ["overview", "agent-metrics", "skills", "galaxy", "security", "settings"]],
    ]);
    const all = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.id));
    for (const old of V1_DEFAULT) expect(all).toContain(old === "dashboard" ? "overview" : old);
  });
});

describe("migrateNavOrder", () => {
  it("a stored order equal to the old default (saved on first mount, never reordered) → the new default", () => {
    expect(migrateNavOrder(V1_DEFAULT)).toEqual(defaultOrder());
    expect(migrateNavOrder(V1_DEFAULT.filter((id) => id !== "resources"))).toEqual(defaultOrder());  // pre-Resources
    expect(migrateNavOrder(["plans", ...V1_DEFAULT.filter((id) => id !== "changes" && id !== "audit")]))
      .toEqual(defaultOrder());  // pre-2.6.1 "plans" in the changes slot is still the default
  });
  it("nothing stored, or garbage → the new default", () => {
    expect(migrateNavOrder(null)).toEqual(defaultOrder());
    expect(migrateNavOrder("chat")).toEqual(defaultOrder());
    expect(migrateNavOrder([1, 2])).toEqual(defaultOrder());
  });
  it("a reordered list keeps the user's relative order inside each group", () => {
    const own = ["security", "galaxy", "reports", "chat", "issues", "schedules", "resources", "audit", "changes",
                 "dashboard", "agent-metrics", "skills"];
    expect(migrateNavOrder(own)).toEqual({
      daily: ["reports", "chat", "issues"],
      tools: ["schedules", "resources", "audit", "changes"],
      administration: ["security", "galaxy", "overview", "agent-metrics", "skills", "settings"],
    });
  });
});

describe("normalizeOrder / moveWithinGroup", () => {
  it("fills entries added since the order was saved and drops ones that are gone", () => {
    expect(normalizeOrder({ daily: ["reports", "gone", "chat"] }).daily).toEqual(["reports", "chat", "issues"]);
    expect(normalizeOrder(undefined)).toEqual(defaultOrder());
  });
  it("moves only inside one group", () => {
    const o = moveWithinGroup(defaultOrder(), "tools", "schedules", "changes");
    expect(o.tools).toEqual(["schedules", "changes", "audit", "resources"]);
    expect(o.daily).toEqual(defaultOrder().daily);
  });
});

describe("entryForPath", () => {
  it.each([
    ["/app/chat/abc", "daily", "chat"], ["/app/issues/5", "daily", "issues"], ["/app/signals", "daily", "issues"],
    ["/app/changes/3", "tools", "changes"], ["/app/resources/12", "tools", "resources"],
    ["/app/overview", "administration", "overview"], ["/app/skills/linux-admin", "administration", "skills"],
  ])("%s → %s / %s", (path, group, id) => {
    expect(entryForPath(path)).toMatchObject({ group, entry: { id } });
  });
  it("paths of no entry → null (prefix is not enough)", () => {
    expect(entryForPath("/app/no-such-page")).toBeNull();
    expect(entryForPath("/app/chatty")).toBeNull();
  });
});
