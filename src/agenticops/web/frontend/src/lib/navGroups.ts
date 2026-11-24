import { moveId, reorderNavIds } from "@/lib/navOrder";

/** The sidebar of the blue/white workspace (MVP-2.7.0 S2; regrouped by the owner in the MVP-2.8.0 S2 rework):
 *  daily work always open, the collapsible tools, and administration pinned at the sidebar's foot, never folded.
 *  Group ids are the preferences contract's (`nav_groups_open`: tools / administration — the latter no longer folds). */
export type GroupId = "daily" | "tools" | "administration";
export type CollapsibleGroup = Exclude<GroupId, "daily">;

export interface NavEntry {
  id: string;
  to: string;
  icon: string;
  labelKey: string;
  /** Other paths this entry is the home of (highlight + breadcrumb), e.g. Signals belongs to Issues. */
  owns?: string[];
}

export interface NavGroup {
  id: GroupId;
  labelKey: string;
  /** folds behind its heading (only the tools) */
  collapsible: boolean;
  /** sits at the foot of the sidebar's scroll area (administration: users and settings, settings last) */
  bottom: boolean;
  items: NavEntry[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    // MVP-2.8.0: the to-do workbench merged into Issues («在等我», its first tab) — Issues first, then the pages a
    // person works in every day
    id: "daily", labelKey: "nav.group.daily", collapsible: false, bottom: false, items: [
      { id: "issues", to: "/app/issues", icon: "clock", labelKey: "nav.issues", owns: ["/app/signals"] },
      { id: "chat", to: "/app/chat", icon: "chat", labelKey: "nav.chat" },
      // MVP-2.7.0 S3: Changes and Audit are tabs of Plans & changes; their old paths still belong here
      { id: "plans", to: "/app/plans", icon: "clipboard", labelKey: "nav.plans", owns: ["/app/changes", "/app/audit"] },
      { id: "security", to: "/app/security", icon: "shield", labelKey: "nav.security" },
      { id: "reports", to: "/app/reports", icon: "file", labelKey: "nav.reports" },
    ],
  },
  {
    // S2 rework: the owner's order — overview, Galaxy, schedules, resources — then agent metrics and skills
    id: "tools", labelKey: "nav.group.tools", collapsible: true, bottom: false, items: [
      { id: "overview", to: "/app/overview", icon: "grid", labelKey: "nav.overview" },
      { id: "galaxy", to: "/app/galaxy", icon: "galaxy", labelKey: "nav.galaxy" },
      { id: "schedules", to: "/app/schedules", icon: "calendar", labelKey: "nav.schedules" },
      { id: "resources", to: "/app/resources", icon: "server", labelKey: "nav.resources" },
      { id: "agent-metrics", to: "/app/agent-metrics", icon: "barchart", labelKey: "nav.agentMetrics" },
      { id: "skills", to: "/app/skills", icon: "puzzle", labelKey: "nav.skills" },
    ],
  },
  {
    // S2 rework: users (admins only) and settings, settings the very last entry of the sidebar
    id: "administration", labelKey: "nav.group.administration", collapsible: false, bottom: true, items: [
      { id: "users", to: "/app/users", icon: "users", labelKey: "nav.users" },
      { id: "settings", to: "/app/settings", icon: "cog", labelKey: "nav.settings" },
    ],
  },
];

export type NavOrder = Record<GroupId, string[]>;

export function defaultOrder(): NavOrder {
  return Object.fromEntries(NAV_GROUPS.map((g) => [g.id, g.items.map((i) => i.id)])) as NavOrder;
}

/** The one-list sidebar before 2.7.0 (`aiops-nav-order`), and its renames. Settings was pinned outside it. */
export const V1_DEFAULT = [
  "dashboard", "chat", "issues", "changes", "resources", "audit", "schedules", "reports", "agent-metrics", "skills",
  "galaxy", "security",
];
const V1_RENAMES: Record<string, string[]> = { plans: ["changes", "audit"] };
const V1_TO_V2: Record<string, string> = { dashboard: "overview", changes: "plans", audit: "plans" };
// MVP-2.7.0 S3 merged changes + audit into plans: a saved v2 order keeps the entry where changes stood
const V2_RENAMES: Record<string, string[]> = { changes: ["plans"], audit: ["plans"] };

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** The stored v1 order, into groups. The old sidebar saved its default order on first mount, so a stored
 *  order equal to the v1 default means "never reordered" → the new default groups. Otherwise each group keeps
 *  the user's relative order, and items the v1 list never had take their default place. */
export function migrateNavOrder(v1: unknown): NavOrder {
  const defaults = defaultOrder();
  if (!Array.isArray(v1) || !v1.every((x) => typeof x === "string")) return defaults;
  const normalized = reorderNavIds(v1 as string[], V1_DEFAULT, V1_RENAMES);
  // never reordered = the v1 default, wherever the old "plans" entry put changes / audit (both are now "plans")
  const merged = (ids: string[]) => ids.filter((id) => id !== "changes" && id !== "audit");
  if (same(merged(normalized), merged(V1_DEFAULT))) return defaults;
  const renamed = [...new Set(normalized.map((id) => V1_TO_V2[id] ?? id))];
  const out = {} as NavOrder;
  for (const g of NAV_GROUPS) {
    const ids = g.items.map((i) => i.id);
    // entries the v1 list never had take their default places at the end (Settings, pinned at the v1 foot, last —
    // where the user last saw it)
    const added = ids.filter((id) => !renamed.includes(id));
    out[g.id] = [...renamed.filter((id) => ids.includes(id)), ...added];
  }
  return out;
}

/** MVP-2.8.0: the to-do workbench merged into Issues — a stored order that has it gets Issues in its slot (an
 *  order saved with the S2 default becomes the new default; a custom one keeps everything else where it was).
 *  A plain rename is not enough: de-duplication would keep an earlier Issues where it was. */
function issuesIntoInboxSlot(ids: string[]): string[] {
  if (!ids.includes("inbox")) return ids;
  const out = ids.filter((id) => id !== "issues");
  out.splice(out.indexOf("inbox"), 1, "issues");
  return out;
}

/** A stored v2 order made safe against entries added or removed since it was saved. */
export function normalizeOrder(stored: unknown): NavOrder {
  const defaults = defaultOrder();
  const s = (stored && typeof stored === "object" ? stored : {}) as Partial<Record<GroupId, unknown>>;
  const out = {} as NavOrder;
  for (const g of NAV_GROUPS) {
    const v = s[g.id];
    const ids = Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
    out[g.id] = reorderNavIds(issuesIntoInboxSlot(ids), defaults[g.id], V2_RENAMES);
  }
  return out;
}

export function moveWithinGroup(order: NavOrder, group: GroupId, sourceId: string, targetId: string): NavOrder {
  return { ...order, [group]: moveId(order[group], sourceId, targetId) };
}

const owns = (path: string, base: string) => path === base || path.startsWith(`${base}/`);

/** The entry (and its group) a path belongs to — the sidebar highlight, the auto-opened group and the
 *  breadcrumb read this. null for paths that belong to no entry (the 404 page). */
export function entryForPath(pathname: string): { group: GroupId; entry: NavEntry } | null {
  for (const g of NAV_GROUPS) {
    for (const entry of g.items) {
      if (owns(pathname, entry.to) || (entry.owns ?? []).some((b) => owns(pathname, b))) return { group: g.id, entry };
    }
  }
  return null;
}

/** The top bar's breadcrumb for a path: the section's label key and, on a detail page, the object's short
 *  reference (I#5, C#3, R#12 — R# is a resource, so a report is just #7). null section = no entry (404). */
export function breadcrumbFor(pathname: string): { sectionKey: string | null; object: string | null } {
  if (pathname === "/app/signals" || pathname.startsWith("/app/signals/")) return { sectionKey: "signals.title", object: null };
  if (pathname === "/app/account/api-keys") return { sectionKey: "apiKeys.title", object: null };  // from the avatar menu
  const hit = entryForPath(pathname);
  if (!hit) return { sectionKey: null, object: null };
  // the path's own base: an owned path (/app/changes/3 under Plans & changes) keeps its own reference
  const base = owns(pathname, hit.entry.to) ? hit.entry.to : (hit.entry.owns ?? []).find((b) => owns(pathname, b)) ?? hit.entry.to;
  const id = pathname.slice(base.length + 1).split("/")[0] || null;
  const refs: Record<string, (v: string) => string> = {
    "/app/issues": (v) => `I#${v}`, "/app/changes": (v) => `C#${v}`, "/app/resources": (v) => `R#${v}`,
    "/app/reports": (v) => `#${v}`, "/app/schedules": (v) => `#${v}`, "/app/skills": (v) => v, "/app/plans": (v) => `#${v}`,
  };
  let raw = id;
  try {
    raw = id && decodeURIComponent(id);
  } catch {
    /* a malformed escape (/app/issues/%) is shown as typed, never thrown into the whole shell */
  }
  const ref = raw && refs[base] ? refs[base](raw) : null;  // chat ids are not shown
  return { sectionKey: hit.entry.labelKey, object: ref };
}

