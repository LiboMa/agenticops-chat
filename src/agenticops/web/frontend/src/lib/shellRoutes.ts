/**
 * What each classic address is inside the new interface (MVP-2.9.0 round 3). The classic pages keep their addresses —
 * notifications, the server's routes and the pages themselves link to them — and the new shell hosts them as they are;
 * where NewUI has a page of its own (an item's story, «waiting on me», the map) the address opens that page instead.
 * Pure, so node can test it; `__tests__/shellRoutes.test.ts` reads App.tsx and fails on a route with no row here.
 */
import { isNewPath } from "@/lib/shellChoice";

export type RouteKind = "hosted" | "native" | "lens" | "outside";

/** Every `path=` of App.tsx. hosted = the classic page under the new frame; native = NewUI's own page by default (the
 *  classic one is reached through an exit, `stayClassic`); lens = NewUI itself; outside = no shell at all. */
export const ROUTE_KINDS: Record<string, RouteKind> = {
  "/app/login": "outside",
  "/app": "hosted",
  "new/*": "lens",
  overview: "hosted",
  chat: "hosted",
  "chat/:sessionId": "hosted",
  inbox: "native",
  issues: "native",
  ":id": "native",                 // issues/:id — the issue's story
  plans: "hosted",
  "plans/:id": "hosted",
  changes: "hosted",               // redirects to the hub's tab
  audit: "hosted",
  "changes/:id": "native",
  schedules: "hosted",
  "schedules/:id": "hosted",
  reports: "hosted",
  "reports/:id": "hosted",
  settings: "hosted",
  "account/api-keys": "hosted",
  users: "hosted",
  resources: "hosted",
  signals: "hosted",
  "resources/:id": "hosted",
  "agent-metrics": "hosted",
  skills: "hosted",
  "skills/:name": "hosted",
  galaxy: "native",
  security: "hosted",
  "*": "hosted",
};

export type FrameMode = "lens" | "hosted";

/** Under the new frame: one of NewUI's own lenses, or a classic page it hosts. */
export function frameMode(pathname: string): FrameMode {
  return isNewPath(pathname) ? "lens" : "hosted";
}

const ID = "([1-9]\\d{0,8})";
const ITEM = /^[IC][1-9]\d{0,8}$/;

/** The NewUI address a classic one opens by default, or null = host the classic page. The link keeps what it named
 *  (the item, the focused resource); what only the classic page understands (a phase anchor, a list filter) is dropped. */
export function nativeTarget(pathname: string, search: string, _hash: string): string | null {
  const path = pathname.replace(/\/+$/, "");
  let m = new RegExp(`^/app/issues/${ID}$`).exec(path);
  if (m) return `/app/new/story/I${m[1]}`;
  m = new RegExp(`^/app/changes/${ID}$`).exec(path);
  if (m) return `/app/new/story/C${m[1]}`;
  const params = new URLSearchParams(search);
  if (path === "/app/inbox" || path === "/app/issues") {
    const view = params.get("view");
    // «waiting on me» (the list's default) is the Decide lens; the other views of the list stay the classic list
    if (path === "/app/issues" && view !== null && view !== "waiting" && view !== "mine") return null;
    const item = params.get("item") ?? "";
    return ITEM.test(item) ? `/app/new/decide/${item}` : "/app/new/decide";
  }
  if (path === "/app/galaxy") {
    const focus = /^(?:res:|r#?)?([1-9]\d{0,8})$/i.exec(params.get("focus") ?? "");
    return focus ? `/app/new/world?sel=${focus[1]}` : "/app/new/world";
  }
  return null;
}

export type ClassicSection = "issues" | "changes" | "galaxy";

/** The router state of a link that means the classic page itself (`<Link to=… state={CLASSIC_EXIT}>`). */
export const CLASSIC_EXIT = { classic: true } as const;

/** The group of classic pages an address belongs to, for the ones NewUI replaces by default. */
export function sectionOf(pathname: string): ClassicSection | null {
  const path = pathname.replace(/\/+$/, "");
  if (path === "/app/issues" || path.startsWith("/app/issues/") || path === "/app/inbox") return "issues";
  if (/^\/app\/changes\/[^/]+$/.test(path)) return "changes";
  if (path === "/app/galaxy") return "galaxy";
  return null;
}

/** The way out to the classic page. NewUI's own exits — «open the classic page» on a story, the one action of an item
 *  kind this client does not know, the classic map (where the graph is rebuilt) — navigate with `state.classic`: the
 *  address is then hosted as it is, and stays so while the person moves inside that section (the classic issue list
 *  links to its issues without saying anything). Leaving the section closes it. `prev` = the answer for the address
 *  before; asking twice for one address gives the same answer. */
export function stayClassic(prev: ClassicSection | null, loc: { pathname: string; state: unknown }): ClassicSection | null {
  const section = sectionOf(loc.pathname);
  if (section === null) return null;
  const asked = !!loc.state && typeof loc.state === "object" && (loc.state as { classic?: unknown }).classic === true;
  return asked || prev === section ? section : null;
}
