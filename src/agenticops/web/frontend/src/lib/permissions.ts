/** Viewer accounts (read-only). The server is the boundary — APIAuthMiddleware refuses every write a viewer sends
 *  (403, code `read_only`); the UI only stops offering them. */
type BootLike = {
  auth_enabled?: boolean;
  user?: { read_only?: boolean; can_view_settings?: boolean; is_admin?: boolean } | null;
} | undefined;

export function isReadOnly(boot: BootLike): boolean {
  return !!boot?.auth_enabled && !!boot.user?.read_only;
}

/** Settings is offered to writers, and to a viewer whose account may view it (read-only, `settings_read`). */
export function canViewSettings(boot: BootLike): boolean {
  return !isReadOnly(boot) || !!boot?.user?.can_view_settings;
}

/** User management (MVP-2.8.0 S2 rework) is an admin's when sign-in is on; with it off every signed-in person is
 *  treated as an admin (roles are not enforced), as the server's `/api/users` does. */
export function canManageUsers(boot: BootLike): boolean {
  return !boot?.auth_enabled || !!boot.user?.is_admin;
}

/** The only navigation entries ever hidden: Settings and Users, each by who may open it. */
export function navItemVisible(id: string, can: { settings: boolean; users: boolean }): boolean {
  if (id === "settings") return can.settings;
  if (id === "users") return can.users;
  return true;
}

/** On a work item's status line a viewer keeps only what navigates (Ask Agent); every other action writes. */
export function viewerActions<T extends { key: string }>(menu: T[]): T[] {
  return menu.filter((action) => action.key === "askAgent");
}
