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

/** The Settings route (MVP-2.9.0 N27): nothing is drawn while the sign-in details are on their way — a viewer who
 *  typed the address saw the page, and two refused requests, for the moment before «not found». When no details
 *  will come (sign-in off: the request is never made) the page is open, as it was. */
export function settingsGate(boot: { data: BootLike; isLoading: boolean }): "wait" | "open" | "notFound" {
  if (boot.isLoading) return "wait";
  return canViewSettings(boot.data) ? "open" : "notFound";
}

/** User management (MVP-2.8.0 S2 rework) is the signed-in user's own admin flag, with sign-in on or off — as the
 *  server's `/api/users` (review: with it off a viewer could take the admin over, and that persisted). Fails closed
 *  until bootstrap has loaded, so a non-admin never sees the entry or the page flash. */
export function canManageUsers(boot: BootLike): boolean {
  return !!boot?.user?.is_admin;
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
