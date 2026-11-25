import type { UserRole, UserRow } from "@/api/types";

/** The user management page (MVP-2.8.0 S2 rework). The server decides who may and what is allowed
 *  (services/user_admin); these only shape what the page shows. */

export type RoleFilter = "all" | UserRole;
export type StatusFilter = "all" | "active" | "disabled";
export type RowAction = "reset" | "newKey" | "role" | "disable" | "enable" | "delete";

/** The role in words: admin, writer, viewer, or a viewer who may view Settings. */
export function roleKey(row: Pick<UserRow, "role" | "settings_view">): string {
  if (row.role === "viewer" && row.settings_view) return "users.role.viewerSettings";
  return `users.role.${row.role}`;
}

/** Search (sign-in or display name, any case) and the role / status filters — a handful of users, in the browser. */
export function filterUsers(rows: UserRow[], f: { q: string; role: RoleFilter; status: StatusFilter }): UserRow[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter((u) =>
    (!q || u.email.toLowerCase().includes(q) || (u.name ?? "").toLowerCase().includes(q))
    && (f.role === "all" || u.role === f.role)
    && (f.status === "all" || (f.status === "active") === u.is_active));
}

/** One row of icon buttons (MVP-2.8.0, owner: «生成密钥，修改密码放一排»): the credentials (reset the password, issue a
 *  key), then the account (role, disable / enable, delete). Never your own account (the server refuses disabling,
 *  demoting or deleting yourself) nor the last active admin's; a disabled user has no credentials to manage. */
export function rowActions(row: Pick<UserRow, "id" | "is_active">, meId: number | null,
                           opts: { lastActiveAdmin: boolean }): { credential: RowAction[]; account: RowAction[] } {
  if (meId !== null && row.id === meId) return { credential: ["reset", "newKey"], account: [] };
  if (!row.is_active) return { credential: [], account: ["enable", "delete"] };
  if (opts.lastActiveAdmin) return { credential: ["reset", "newKey"], account: [] };
  return { credential: ["reset", "newKey"], account: ["role", "disable", "delete"] };
}

/** The one active admin, when there is exactly one (the server keeps it: never demoted, disabled or deleted). */
export function lastActiveAdminId(rows: Pick<UserRow, "id" | "role" | "is_active">[]): number | null {
  const admins = rows.filter((u) => u.role === "admin" && u.is_active);
  return admins.length === 1 ? admins[0].id : null;
}

/** The «API 密钥» column: «N 个有效 ▸» or «无». */
export function keysLabel(n: number, t: (k: string) => string): string {
  return n > 0 ? t("users.keys.label").replace("{n}", String(n)) : t("users.keys.none");
}

/** A worded refusal that names what is in the way (has_open_requests: «C#3, C#5»). */
export function fillRefusal(text: string, data: Record<string, unknown> | undefined): string {
  const refs = data?.refs;
  return Array.isArray(refs) ? text.replace("{refs}", refs.map(String).join(", ")) : text;
}

/** Why a password the admin typed would be refused, or null (MVP-2.9.0 N34). The same rule as the server's
 *  auth.service.password_problem — 8–128 characters (code points, as Python counts them), not only whitespace, no
 *  control characters — only to word it before sending; the server decides. */
export type PasswordProblem = "too_short" | "too_long" | "blank" | "control_character";
export const PASSWORD_MIN_CHARS = 8;
export const PASSWORD_MAX_CHARS = 128;

export function passwordProblem(pw: string): PasswordProblem | null {
  const chars = [...pw].length;
  if (chars < PASSWORD_MIN_CHARS) return "too_short";
  if (chars > PASSWORD_MAX_CHARS) return "too_long";
  if (!pw.trim()) return "blank";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f-\u009f]/.test(pw)) return "control_character";
  return null;
}

/** What a reset sends: nothing for a generated password; the typed one once it meets the rule and both entries
 *  agree (the rule is worded first). */
export type ResetMode = "generate" | "typed";
export type ResetPayload =
  | { ok: true; body: { password?: string } }
  | { ok: false; reason: PasswordProblem | "mismatch" };

export function resetPayload(mode: ResetMode, pw: string, confirm: string): ResetPayload {
  if (mode === "generate") return { ok: true, body: {} };
  const problem = passwordProblem(pw);
  if (problem) return { ok: false, reason: problem };
  if (pw !== confirm) return { ok: false, reason: "mismatch" };
  return { ok: true, body: { password: pw } };
}
