import { describe, it, expect } from "vitest";
import { NAV_GROUPS, V1_DEFAULT, breadcrumbFor, defaultOrder, entryForPath, migrateNavOrder, moveWithinGroup, normalizeOrder } from "@/lib/navGroups";

describe("NAV_GROUPS — the blue/white sidebar", () => {
  it("MVP-2.8.0 S2: daily work = workbench, chat, issues, plans & changes, security, reports; every old entry kept", () => {
    expect(NAV_GROUPS.map((g) => [g.id, g.items.map((i) => i.id)])).toEqual([
      ["daily", ["inbox", "chat", "issues", "plans", "security", "reports"]],
      ["tools", ["schedules", "resources", "settings"]],
      ["administration", ["overview", "agent-metrics", "skills", "galaxy"]],
    ]);
    expect(NAV_GROUPS[0].items[0]).toMatchObject({ id: "inbox", to: "/app/inbox", icon: "inbox" });
    const all = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.id));
    const renamed: Record<string, string> = { dashboard: "overview", changes: "plans", audit: "plans" };  // S3 merged changes + audit
    for (const old of V1_DEFAULT) expect(all).toContain(renamed[old] ?? old);
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
      daily: ["security", "reports", "chat", "issues", "plans", "inbox"],
      tools: ["schedules", "resources", "settings"],
      administration: ["galaxy", "overview", "agent-metrics", "skills"],
    });
  });
});

describe("normalizeOrder / moveWithinGroup", () => {
  it("a v2 order saved with changes + audit keeps the merged entry where changes was", () => {
    expect(normalizeOrder({ daily: ["chat", "changes", "issues", "audit"] }).daily)
      .toEqual(["inbox", "chat", "plans", "security", "reports", "issues"]);
  });
  it("MVP-2.8.0 S2: a v2 order saved before the move — plans and security join daily work, settings joins the tools, the workbench comes first, the user's own order stays", () => {
    const saved = { daily: ["reports", "chat", "issues"], tools: ["schedules", "plans", "resources"],
                    administration: ["galaxy", "security", "overview", "agent-metrics", "skills", "settings"] };
    expect(normalizeOrder(saved)).toEqual({
      daily: ["inbox", "reports", "chat", "issues", "plans", "security"],
      tools: ["schedules", "resources", "settings"],
      administration: ["galaxy", "overview", "agent-metrics", "skills"],
    });
  });
  it("old change paths belong to Plans & changes, with the right reference", () => {
    expect(entryForPath("/app/changes/3")?.entry.id).toBe("plans");
    expect(entryForPath("/app/inbox")?.entry.id).toBe("inbox");
    expect(breadcrumbFor("/app/changes/3")).toEqual({ sectionKey: "nav.plans", object: "C#3" });
    expect(breadcrumbFor("/app/plans/12")).toEqual({ sectionKey: "nav.plans", object: "#12" });
    expect(breadcrumbFor("/app/audit")).toEqual({ sectionKey: "nav.plans", object: null });
  });
  it("fills entries added since the order was saved and drops ones that are gone", () => {
    expect(normalizeOrder({ daily: ["reports", "gone", "chat"] }).daily)
      .toEqual(["inbox", "reports", "chat", "issues", "plans", "security"]);
    expect(normalizeOrder(undefined)).toEqual(defaultOrder());
  });
  it("moves only inside one group", () => {
    const o = moveWithinGroup(defaultOrder(), "tools", "settings", "schedules");
    expect(o.tools).toEqual(["settings", "schedules", "resources"]);
    expect(o.daily).toEqual(defaultOrder().daily);
  });
});

describe("entryForPath", () => {
  it.each([
    ["/app/chat/abc", "daily", "chat"], ["/app/issues/5", "daily", "issues"], ["/app/signals", "daily", "issues"],
    ["/app/changes/3", "daily", "plans"], ["/app/plans/9", "daily", "plans"], ["/app/resources/12", "tools", "resources"],
    ["/app/inbox", "daily", "inbox"], ["/app/security", "daily", "security"], ["/app/settings", "tools", "settings"],
    ["/app/overview", "administration", "overview"], ["/app/skills/linux-admin", "administration", "skills"],
  ])("%s → %s / %s", (path, group, id) => {
    expect(entryForPath(path)).toMatchObject({ group, entry: { id } });
  });
  it("paths of no entry → null (prefix is not enough)", () => {
    expect(entryForPath("/app/no-such-page")).toBeNull();
    expect(entryForPath("/app/chatty")).toBeNull();
  });
});

describe("breadcrumbFor", () => {
  it.each([
    ["/app/issues", "nav.issues", null], ["/app/issues/5", "nav.issues", "I#5"], ["/app/changes/3", "nav.plans", "C#3"], ["/app/plans/12", "nav.plans", "#12"],
    ["/app/resources/12", "nav.resources", "R#12"], ["/app/reports/7", "nav.reports", "#7"],
    ["/app/skills/linux-admin", "nav.skills", "linux-admin"], ["/app/chat/3f2a-uuid", "nav.chat", null],
    ["/app/signals", "signals.title", null], ["/app/overview", "nav.overview", null], ["/app/nope", null, null],
  ])("%s → %s %s", (path, sectionKey, object) => {
    expect(breadcrumbFor(path)).toEqual({ sectionKey, object });
  });
  it("a malformed escape is shown as typed, not thrown (it would blank the app)", () => {
    expect(breadcrumbFor("/app/issues/%")).toEqual({ sectionKey: "nav.issues", object: "I#%" });
    expect(breadcrumbFor("/app/skills/%E0")).toEqual({ sectionKey: "nav.skills", object: "%E0" });
  });
});

import { isRailRoute } from "@/lib/navGroups";
describe("isRailRoute (2026-11-07: Chat gets the icon rail)", () => {
  it("chat routes only", () => {
    expect(isRailRoute("/app/chat")).toBe(true);
    expect(isRailRoute("/app/chat/abc")).toBe(true);
    expect(isRailRoute("/app/chats")).toBe(false);
    expect(isRailRoute("/app/issues")).toBe(false);
  });
});
