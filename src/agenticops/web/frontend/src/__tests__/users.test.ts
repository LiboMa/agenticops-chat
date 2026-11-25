import { describe, expect, it } from "vitest";
import type { UserRow } from "@/api/types";
import { fillRefusal, filterUsers, keysLabel, lastActiveAdminId, passwordProblem, resetPayload, roleKey, rowActions } from "@/lib/users";
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

/** A password the admin types at a reset (MVP-2.9.0 N34) — the same rule the server checks
 *  (auth.service.password_problem); the page only words it, the server is the boundary. */
describe("passwordProblem — 8–128 characters, not only spaces, no control characters", () => {
  it("takes what meets the rule", () => {
    for (const ok of ["12345678", "x".repeat(128), "pass phrase with spaces", "密码要八个字符以上", "abc​defgh"]) {
      expect(passwordProblem(ok)).toBeNull();
    }
  });
  it("words what does not", () => {
    expect(passwordProblem("1234567")).toBe("too_short");
    expect(passwordProblem("")).toBe("too_short");
    expect(passwordProblem("x".repeat(129))).toBe("too_long");
    expect(passwordProblem("        ")).toBe("blank");
    expect(passwordProblem("tab\there!!")).toBe("control_character");
    expect(passwordProblem("abc\u007fdefgh")).toBe("control_character");
    expect(passwordProblem("abc\u0085defgh")).toBe("control_character");
  });
  it("counts characters as the server does (code points, not UTF-16 units)", () => {
    expect(passwordProblem("😀".repeat(7))).toBe("too_short");      // 14 UTF-16 units, 7 characters
    expect(passwordProblem("😀".repeat(8))).toBeNull();
    expect(passwordProblem("😀".repeat(129))).toBe("too_long");
  });
});

describe("resetPayload — what a reset sends", () => {
  it("a generated password sends nothing", () => {
    expect(resetPayload("generate", "whatever", "")).toEqual({ ok: true, body: {} });
  });
  it("a typed one sends the password once both entries agree and it meets the rule", () => {
    expect(resetPayload("typed", "Correct-horse-9", "Correct-horse-9")).toEqual({ ok: true, body: { password: "Correct-horse-9" } });
  });
  it("the rule comes first, then the two entries", () => {
    expect(resetPayload("typed", "short", "short")).toEqual({ ok: false, reason: "too_short" });
    expect(resetPayload("typed", "Correct-horse-9", "Correct-horse-8")).toEqual({ ok: false, reason: "mismatch" });
    expect(resetPayload("typed", "", "")).toEqual({ ok: false, reason: "too_short" });
  });
  it("every reason has words in both languages", async () => {
    const en = (await import("@/locales/en.json")).default as Record<string, string>;
    for (const reason of ["too_short", "too_long", "blank", "control_character", "mismatch"]) {
      expect((zh as Record<string, string>)[`users.reset.reason.${reason}`]).toBeTruthy();
      expect(en[`users.reset.reason.${reason}`]).toBeTruthy();
    }
  });
});
