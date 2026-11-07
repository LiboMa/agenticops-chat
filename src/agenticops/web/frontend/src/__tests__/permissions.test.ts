import { describe, expect, it } from "vitest";
import { canViewSettings, isReadOnly, navItemVisible, viewerActions } from "@/lib/permissions";

describe("isReadOnly", () => {
  it("is a signed-in viewer only", () => {
    expect(isReadOnly({ auth_enabled: true, user: { read_only: true } })).toBe(true);
    expect(isReadOnly({ auth_enabled: true, user: { read_only: false } })).toBe(false);
    expect(isReadOnly({ auth_enabled: true, user: null })).toBe(false);
    expect(isReadOnly({ auth_enabled: false, user: { read_only: true } })).toBe(false);
    expect(isReadOnly(undefined)).toBe(false);
  });
});

describe("canViewSettings", () => {
  it("is every writer, and a viewer only with can_view_settings", () => {
    expect(canViewSettings({ auth_enabled: true, user: { read_only: false } })).toBe(true);
    expect(canViewSettings({ auth_enabled: false, user: null })).toBe(true);
    expect(canViewSettings({ auth_enabled: true, user: { read_only: true, can_view_settings: true } })).toBe(true);
    expect(canViewSettings({ auth_enabled: true, user: { read_only: true, can_view_settings: false } })).toBe(false);
    expect(canViewSettings({ auth_enabled: true, user: { read_only: true } })).toBe(false);
  });
});

describe("navItemVisible", () => {
  it("hides only Settings, and only when it may not be viewed", () => {
    expect(navItemVisible("settings", false)).toBe(false);
    expect(navItemVisible("settings", true)).toBe(true);
    for (const id of ["chat", "issues", "reports", "plans", "resources", "schedules", "galaxy", "security"]) {
      expect(navItemVisible(id, false)).toBe(true);
    }
  });
});

describe("viewerActions", () => {
  it("keeps only Ask Agent", () => {
    const menu = ["runRca", "markResolved", "dismiss", "askAgent", "reject", "copyAsNew"].map((key) => ({ key }));
    expect(viewerActions(menu)).toEqual([{ key: "askAgent" }]);
    expect(viewerActions([])).toEqual([]);
  });
});
