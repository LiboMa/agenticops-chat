import { NAV_GROUPS, entryForPath, type GroupId } from "@/lib/navGroups";
import { navItemVisible } from "@/lib/permissions";

/** The «pages» menu of NewUI's top bar (round 3): the classic sidebar's own table, so no page becomes unreachable
 *  by click under the new frame — same groups, same order, same rules for who sees Settings and Users. Two entries
 *  differ: the map is not listed («全景» is the map), and «issues» is the classic list of everything («waiting on me»
 *  is the «待决» tab), with Signals — which the classic sidebar reaches through the issue pages — beside it. */
export interface PageEntry {
  id: string;
  to: string;
  labelKey: string;                 // a key of the classic locale files
  /** router state to go with: `classic` keeps the classic page where NewUI has its own (lib/shellRoutes.stayClassic) */
  state?: { classic: true };
}
export interface PageGroup { id: GroupId; labelKey: string; items: PageEntry[] }

export function pagesMenu(can: { settings: boolean; users: boolean }): PageGroup[] {
  return NAV_GROUPS.map((g) => ({
    id: g.id, labelKey: g.labelKey,
    items: g.items.filter((i) => i.id !== "galaxy" && navItemVisible(i.id, can)).flatMap((i): PageEntry[] => (
      i.id === "issues"
        ? [{ id: "issues", to: "/app/issues?view=all", labelKey: i.labelKey, state: { classic: true } },
           { id: "signals", to: "/app/signals", labelKey: "signals.title" }]
        : [{ id: i.id, to: i.to, labelKey: i.labelKey }]
    )),
  })).filter((g) => g.items.length > 0);
}

/** The menu entry an address belongs to (for the mark on the current page); null = none of them. */
export function currentPage(pathname: string): string | null {
  const path = pathname.replace(/\/+$/, "");
  if (path === "/app/signals" || path.startsWith("/app/signals/")) return "signals";
  return entryForPath(path)?.entry.id ?? null;
}
