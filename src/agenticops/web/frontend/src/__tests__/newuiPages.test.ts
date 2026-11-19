import { describe, expect, it } from "vitest";
import { currentPage, pagesMenu } from "@/newui/lib/pages";

const all = { settings: true, users: true };
const ids = (groups: ReturnType<typeof pagesMenu>) => groups.map((g) => [g.id, g.items.map((i) => i.id)]);

describe("pagesMenu — every page is one click away under the new frame", () => {
  it("lists the classic sidebar's sections in its groups and order, signals beside the issues", () => {
    expect(ids(pagesMenu(all))).toEqual([
      ["daily", ["issues", "signals", "chat", "plans", "security", "reports"]],
      ["tools", ["overview", "schedules", "resources", "agent-metrics", "skills"]],
      ["administration", ["users", "settings"]],
    ]);
  });
  it("the map is not listed: «全景» is the map", () => {
    expect(pagesMenu(all).flatMap((g) => g.items).some((i) => i.id === "galaxy" || i.to === "/app/galaxy")).toBe(false);
  });
  it("«issues» is the classic list of everything, entered as a classic page — «waiting on me» is the «待决» tab", () => {
    const issues = pagesMenu(all)[0].items[0];
    expect(issues.to).toBe("/app/issues?view=all");
    expect(issues.state).toEqual({ classic: true });
    expect(pagesMenu(all)[0].items[2].state).toBeUndefined();          // every other page is simply hosted
  });
  it("what the person may not open is not offered, and a group with nothing in it is not shown", () => {
    expect(ids(pagesMenu({ settings: false, users: false })).map(([g]) => g)).toEqual(["daily", "tools"]);
    expect(ids(pagesMenu({ settings: true, users: false }))[2]).toEqual(["administration", ["settings"]]);
  });
  it("every entry is an /app address with a label", () => {
    for (const i of pagesMenu(all).flatMap((g) => g.items)) {
      expect(i.to).toMatch(/^\/app\/[a-z-]+(\?view=all)?$/);
      expect(i.labelKey).toMatch(/^[a-zA-Z]+\.[a-zA-Z.]+$/);
    }
  });
});

describe("currentPage — the entry the address belongs to", () => {
  it.each([
    ["/app/reports", "reports"], ["/app/reports/7", "reports"], ["/app/signals", "signals"], ["/app/issues/12", "issues"],
    ["/app/changes/3", "plans"], ["/app/audit", "plans"], ["/app/chat/abc", "chat"], ["/app/settings", "settings"],
    ["/app/agent-metrics", "agent-metrics"], ["/app/skills/x", "skills"],
  ])("%s → %s", (path, id) => expect(currentPage(path)).toBe(id));
  it("a lens, the keys page and an unknown address belong to none", () => {
    for (const p of ["/app/new/decide", "/app/account/api-keys", "/app/nope", "/app"]) expect(currentPage(p)).toBeNull();
  });
});
