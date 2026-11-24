import { describe, expect, it } from "vitest";
import type { UserRow } from "@/api/types";
import { fillRefusal, filterUsers, keysLabel, lastActiveAdminId, roleKey, rowActions } from "@/lib/users";
import zh from "@/locales/zh.json";

const row = (over: Partial<UserRow> = {}): UserRow => ({
  id: 2, email: "ops-lin", name: "Lin Yue", role: "writer", settings_view: false, is_active: true,
  last_login_at: null, created_at: "2026-11-09T01:00:00", ...over,
});

/** The user management page (MVP-2.8.0 S2 rework). */
describe("roleKey — the four roles in words", () => {
  it("admin, writer, viewer, viewer who may view Settings", () => {
    expect(roleKey(row({ role: "admin" }))).toBe("users.role.admin");
    expect(roleKey(row({ role: "writer" }))).toBe("users.role.writer");
    expect(roleKey(row({ role: "viewer" }))).toBe("users.role.viewer");
    expect(roleKey(row({ role: "viewer", settings_view: true }))).toBe("users.role.viewerSettings");
  });
});

describe("filterUsers — search and the two filters, in the browser", () => {
  const rows = [
    row({ id: 1, email: "malibo", name: "Ma Libo", role: "admin" }),
    row({ id: 2, email: "ops-lin", name: "Lin Yue", role: "writer" }),
    row({ id: 3, email: "viewer", name: null, role: "viewer", is_active: false }),
    row({ id: 4, email: "editor", name: "Zhou", role: "viewer", settings_view: true }),
  ];
  const ids = (r: UserRow[]) => r.map((u) => u.id);
  it("matches the sign-in name or the display name, any case", () => {
    expect(ids(filterUsers(rows, { q: "LIN", role: "all", status: "all" }))).toEqual([2]);
    expect(ids(filterUsers(rows, { q: "zhou", role: "all", status: "all" }))).toEqual([4]);
    expect(ids(filterUsers(rows, { q: "  ", role: "all", status: "all" }))).toEqual([1, 2, 3, 4]);
  });
  it("a viewer who may view Settings is a viewer; the status filter reads is_active", () => {
    expect(ids(filterUsers(rows, { q: "", role: "viewer", status: "all" }))).toEqual([3, 4]);
    expect(ids(filterUsers(rows, { q: "", role: "all", status: "disabled" }))).toEqual([3]);
    expect(ids(filterUsers(rows, { q: "", role: "viewer", status: "active" }))).toEqual([4]);
  });
});

describe("rowActions — one row of icons: the credentials, then the account (MVP-2.8.0 user management)", () => {
  const none = { lastActiveAdmin: false };
  it("yourself: your password and your keys, never your own account", () => {
    expect(rowActions(row({ id: 7, role: "admin" }), 7, none)).toEqual({ credential: ["reset", "newKey"], account: [] });
  });
  it("anyone else: password and keys, then role, disable, delete", () => {
    expect(rowActions(row(), 1, none)).toEqual({ credential: ["reset", "newKey"], account: ["role", "disable", "delete"] });
    expect(rowActions(row(), null, none)).toEqual({ credential: ["reset", "newKey"], account: ["role", "disable", "delete"] });
  });
  it("a disabled user: no credentials (they cannot sign in), enable or delete", () => {
    expect(rowActions(row({ is_active: false }), 1, none)).toEqual({ credential: [], account: ["enable", "delete"] });
  });
  it("the last active admin: never demoted, disabled or deleted", () => {
    expect(rowActions(row({ role: "admin" }), 1, { lastActiveAdmin: true })).toEqual({ credential: ["reset", "newKey"], account: [] });
  });
  it("the last active admin is the one active admin", () => {
    const rows = [row({ id: 1, role: "admin" }), row({ id: 2, role: "admin", is_active: false }), row({ id: 3 })];
    expect(lastActiveAdminId(rows)).toBe(1);
    expect(lastActiveAdminId([...rows, row({ id: 4, role: "admin" })])).toBeNull();
  });
});

describe("the «API 密钥» column and worded refusals", () => {
  const t = (k: string) => (zh as Record<string, string>)[k] ?? k;
  it("«无» or the active count", () => {
    expect(keysLabel(0, t)).toBe(t("users.keys.none"));
    expect(keysLabel(3, t)).toContain("3");
  });
  it("a refusal that names the change requests in the way", () => {
    expect(fillRefusal("还有 {refs} 在等他", { refs: ["C#3", "C#5"] })).toBe("还有 C#3, C#5 在等他");
    expect(fillRefusal("没有占位", undefined)).toBe("没有占位");
  });
});
