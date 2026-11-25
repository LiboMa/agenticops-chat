import { describe, expect, it } from "vitest";
import { canChangeModels, canManageUsers, canViewSettings, isReadOnly, navItemVisible, settingsGate, viewerActions } from "@/lib/permissions";

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
  it("the signed-in user's own admin flag, with sign-in on or off (review: with it off a viewer took the admin over)", () => {
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: true } })).toBe(true);
    expect(canManageUsers({ auth_enabled: false, user: { is_admin: true } })).toBe(true);
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: false } })).toBe(false);
    expect(canManageUsers({ auth_enabled: false, user: { is_admin: false } })).toBe(false);
    expect(canManageUsers({ auth_enabled: true, user: { is_admin: false, read_only: true } })).toBe(false);
    expect(canManageUsers({ auth_enabled: true, user: null })).toBe(false);
  });
  it("fails closed until bootstrap has loaded (a viewer saw «用户管理» and «新建用户» flash)", () => {
    expect(canManageUsers(undefined)).toBe(false);
  });
});

describe("viewerActions", () => {
  it("keeps only Ask Agent", () => {
    const menu = ["runRca", "markResolved", "dismiss", "askAgent", "reject", "copyAsNew"].map((key) => ({ key }));
    expect(viewerActions(menu)).toEqual([{ key: "askAgent" }]);
    expect(viewerActions([])).toEqual([]);
  });
});

describe("settingsGate (MVP-2.9.0 N27)", () => {
  const viewer = { auth_enabled: true, user: { read_only: true } };
  it("draws nothing while the sign-in details are on their way (a viewer saw Settings, and two refused requests, before «not found»)", () => {
    expect(settingsGate({ data: undefined, isLoading: true })).toBe("wait");
  });
  it("then opens for a writer and for a viewer who may view Settings, and is «not found» for any other viewer", () => {
    expect(settingsGate({ data: { auth_enabled: true, user: { read_only: false } }, isLoading: false })).toBe("open");
    expect(settingsGate({ data: { auth_enabled: true, user: { read_only: true, can_view_settings: true } }, isLoading: false })).toBe("open");
    expect(settingsGate({ data: viewer, isLoading: false })).toBe("notFound");
  });
  it("stays open when no details will come (sign-in off: the request is never made) or they could not be read", () => {
    expect(settingsGate({ data: undefined, isLoading: false })).toBe("open");
  });
  it("a refresh in the background does not blank the page", () => {
    expect(settingsGate({ data: viewer, isLoading: false })).toBe("notFound");
    expect(settingsGate({ data: { auth_enabled: true, user: { read_only: false } }, isLoading: false })).toBe("open");
  });
});

describe("canChangeModels (MVP-2.9.0 N35)", () => {
  it("is an administrator's with sign-in on, anyone's with it off", () => {
    expect(canChangeModels({ auth_enabled: true, user: { is_admin: true } })).toBe(true);
    expect(canChangeModels({ auth_enabled: true, user: { is_admin: false } })).toBe(false);
    expect(canChangeModels({ auth_enabled: true, user: null })).toBe(false);
    expect(canChangeModels({ auth_enabled: false, user: null })).toBe(true);
    expect(canChangeModels(undefined)).toBe(true);
  });
});
