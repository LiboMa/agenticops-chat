import { describe, expect, it } from "vitest";
import { canManageUsers, canViewSettings, isReadOnly, navItemVisible, viewerActions } from "@/lib/permissions";

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
  it("hides Settings when it may not be viewed and Users when they may not be managed; nothing else", () => {
    expect(navItemVisible("settings", { settings: false, users: true })).toBe(false);
    expect(navItemVisible("settings", { settings: true, users: false })).toBe(true);
    expect(navItemVisible("users", { settings: true, users: false })).toBe(false);
    expect(navItemVisible("users", { settings: false, users: true })).toBe(true);
    for (const id of ["chat", "issues", "reports", "plans", "resources", "schedules", "galaxy", "security", "skills"]) {
      expect(navItemVisible(id, { settings: false, users: false })).toBe(true);
    }
  });
});

describe("canManageUsers (S2 rework)", () => {
  it("an admin when sign-in is on; everyone signed in when it is off (roles are not enforced then)", () => {
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: true } })).toBe(true);
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: false } })).toBe(false);
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: false, read_only: true } })).toBe(false);
    expect(canManageUsers({ auth_enabled: true, user: null })).toBe(false);
    expect(canManageUsers({ auth_enabled: false, user: { is_admin: false } })).toBe(true);
  });
});

describe("viewerActions", () => {
  it("keeps only Ask Agent", () => {
    const menu = ["runRca", "markResolved", "dismiss", "askAgent", "reject", "copyAsNew"].map((key) => ({ key }));
    expect(viewerActions(menu)).toEqual([{ key: "askAgent" }]);
    expect(viewerActions([])).toEqual([]);
  });
});
