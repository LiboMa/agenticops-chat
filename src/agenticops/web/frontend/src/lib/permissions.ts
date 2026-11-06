/** Viewer accounts (read-only). The server is the boundary — APIAuthMiddleware refuses every write a viewer sends
 *  (403, code `read_only`); the UI only stops offering them. */
type BootLike = {
  auth_enabled?: boolean;
  user?: { read_only?: boolean; can_view_settings?: boolean } | null;
} | undefined;

export function isReadOnly(boot: BootLike): boolean {
  return !!boot?.auth_enabled && !!boot.user?.read_only;
}

/** Settings is offered to writers, and to a viewer whose account may view it (read-only, `settings_read`). */
export function canViewSettings(boot: BootLike): boolean {
  return !isReadOnly(boot) || !!boot?.user?.can_view_settings;
}

/** Settings is the only navigation entry ever hidden. */
export function navItemVisible(id: string, settingsVisible: boolean): boolean {
  return id !== "settings" || settingsVisible;
}

/** On a work item's status line a viewer keeps only what navigates (Ask Agent); every other action writes. */
export function viewerActions<T extends { key: string }>(menu: T[]): T[] {
  return menu.filter((action) => action.key === "askAgent");
}
