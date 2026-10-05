import { moveId, reorderNavIds } from "@/lib/navOrder";

/** The sidebar of the blue/white workspace (MVP-2.7.0 S2): daily work always open, two collapsible groups.
 *  Group ids are the preferences contract's (`nav_groups_open`: tools / administration). */
export type GroupId = "daily" | "tools" | "administration";
export type CollapsibleGroup = Exclude<GroupId, "daily">;

export interface NavEntry {
  id: string;
  to: string;
  icon: string;
  labelKey: string;
  badge?: boolean;
  /** Other paths this entry is the home of (highlight + breadcrumb), e.g. Signals belongs to Issues. */
  owns?: string[];
}

export interface NavGroup {
  id: GroupId;
  labelKey: string;
  items: NavEntry[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "daily", labelKey: "nav.group.daily", items: [
      { id: "chat", to: "/app/chat", icon: "chat", labelKey: "nav.chat" },
      { id: "issues", to: "/app/issues", icon: "clock", labelKey: "nav.issues", badge: true, owns: ["/app/signals"] },
      { id: "reports", to: "/app/reports", icon: "file", labelKey: "nav.reports" },
    ],
  },
  {
    // S3 merges Changes + Audit into "Plans & changes"
    id: "tools", labelKey: "nav.group.tools", items: [
      { id: "changes", to: "/app/changes", icon: "clipboard", labelKey: "nav.changes" },
      { id: "audit", to: "/app/audit", icon: "audit", labelKey: "nav.audit" },
      { id: "resources", to: "/app/resources", icon: "server", labelKey: "nav.resources" },
      { id: "schedules", to: "/app/schedules", icon: "calendar", labelKey: "nav.schedules" },
    ],
  },
  {
    id: "administration", labelKey: "nav.group.administration", items: [
      { id: "overview", to: "/app/overview", icon: "grid", labelKey: "nav.overview" },
      { id: "agent-metrics", to: "/app/agent-metrics", icon: "barchart", labelKey: "nav.agentMetrics" },
      { id: "skills", to: "/app/skills", icon: "puzzle", labelKey: "nav.skills" },
      { id: "galaxy", to: "/app/galaxy", icon: "galaxy", labelKey: "nav.galaxy" },
      { id: "security", to: "/app/security", icon: "shield", labelKey: "nav.security" },
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
const V1_TO_V2: Record<string, string> = { dashboard: "overview" };

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** The stored v1 order, into groups. The old sidebar saved its default order on first mount, so a stored
 *  order equal to the v1 default means "never reordered" → the new default groups. Otherwise each group keeps
 *  the user's relative order, and items the v1 list never had take their default place. */
export function migrateNavOrder(v1: unknown): NavOrder {
  const defaults = defaultOrder();
  if (!Array.isArray(v1) || !v1.every((x) => typeof x === "string")) return defaults;
  const normalized = reorderNavIds(v1 as string[], V1_DEFAULT, V1_RENAMES);
  if (same(normalized, V1_DEFAULT)) return defaults;
  const renamed = normalized.map((id) => V1_TO_V2[id] ?? id);
  const out = {} as NavOrder;
  for (const g of NAV_GROUPS) {
    const ids = g.items.map((i) => i.id);
    // entries the v1 list never had (Settings, pinned at its foot) go last, where the user last saw them
    out[g.id] = [...renamed.filter((id) => ids.includes(id)), ...ids.filter((id) => !renamed.includes(id))];
  }
  return out;
}

/** A stored v2 order made safe against entries added or removed since it was saved. */
export function normalizeOrder(stored: unknown): NavOrder {
  const defaults = defaultOrder();
  const s = (stored && typeof stored === "object" ? stored : {}) as Partial<Record<GroupId, unknown>>;
  const out = {} as NavOrder;
  for (const g of NAV_GROUPS) {
    const v = s[g.id];
    out[g.id] = reorderNavIds(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [], defaults[g.id]);
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
  const hit = entryForPath(pathname);
  if (!hit) return { sectionKey: null, object: null };
  const id = pathname.slice(hit.entry.to.length + 1).split("/")[0] || null;
  const refs: Record<string, (v: string) => string> = {
    issues: (v) => `I#${v}`, changes: (v) => `C#${v}`, resources: (v) => `R#${v}`,
    reports: (v) => `#${v}`, schedules: (v) => `#${v}`, skills: (v) => v,
  };
  let raw = id;
  try {
    raw = id && decodeURIComponent(id);
  } catch {
    /* a malformed escape (/app/issues/%) is shown as typed, never thrown into the whole shell */
  }
  const ref = raw && refs[hit.entry.id] ? refs[hit.entry.id](raw) : null;  // chat ids are not shown
  return { sectionKey: hit.entry.labelKey, object: ref };
}
