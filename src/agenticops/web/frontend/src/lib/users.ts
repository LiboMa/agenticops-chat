import type { UserRole, UserRow } from "@/api/types";

/** The user management page (MVP-2.8.0 S2 rework). The server decides who may and what is allowed
 *  (services/user_admin); these only shape what the page shows. */

export type RoleFilter = "all" | UserRole;
export type StatusFilter = "all" | "active" | "disabled";
export type RowAction = "role" | "reset" | "disable" | "enable";

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

/** Your own row only resets your password (the server refuses disabling or demoting yourself); a disabled user
 *  can only be enabled; anyone else: change role, reset password, disable. */
export function rowActions(row: Pick<UserRow, "id" | "is_active">, meId: number | null): RowAction[] {
  if (meId !== null && row.id === meId) return ["reset"];
  if (!row.is_active) return ["enable"];
  return ["role", "reset", "disable"];
}
