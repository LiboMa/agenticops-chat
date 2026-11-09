import { describe, expect, it } from "vitest";
import type { UserRow } from "@/api/types";
import { filterUsers, roleKey, rowActions } from "@/lib/users";

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

describe("rowActions — what each row offers", () => {
  it("yourself: only reset your password (never disable or demote yourself)", () => {
    expect(rowActions(row({ id: 7, role: "admin" }), 7)).toEqual(["reset"]);
  });
  it("a disabled user: only enable", () => {
    expect(rowActions(row({ is_active: false }), 1)).toEqual(["enable"]);
  });
  it("anyone else: change role, reset password, disable", () => {
    expect(rowActions(row(), 1)).toEqual(["role", "reset", "disable"]);
    expect(rowActions(row(), null)).toEqual(["role", "reset", "disable"]);
  });
});
