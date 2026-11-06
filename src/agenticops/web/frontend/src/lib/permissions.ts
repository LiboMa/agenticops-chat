/** Viewer accounts (read-only). The server is the boundary — APIAuthMiddleware refuses every write a viewer sends
 *  (403, code `read_only`); the UI only stops offering them. */
type BootLike = { auth_enabled?: boolean; user?: { read_only?: boolean } | null } | undefined;

export function isReadOnly(boot: BootLike): boolean {
  return !!boot?.auth_enabled && !!boot.user?.read_only;
}

/** Navigation entries a viewer is not offered: Settings is configuration from end to end. */
const READ_ONLY_HIDDEN_NAV = new Set(["settings"]);

export function navItemVisible(id: string, readOnly: boolean): boolean {
  return !(readOnly && READ_ONLY_HIDDEN_NAV.has(id));
}

/** On a work item's status line a viewer keeps only what navigates (Ask Agent); every other action writes. */
export function viewerActions<T extends { key: string }>(menu: T[]): T[] {
  return menu.filter((action) => action.key === "askAgent");
}
