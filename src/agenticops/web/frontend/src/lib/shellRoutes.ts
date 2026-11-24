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
  "/app/setup": "outside",       // open signed out too
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
    const view = path === "/app/issues" ? params.get("view") : null;
    // the list of everything is NewUI's «all items» table; «failed» is the Decide lens with that filter, «waited long»
    // the lens itself (it has no such filter); a view NewUI has nothing for is the classic page's to handle
    if (view === "all") return itemsAddress(params);
    if (view === "failed") return "/app/new/decide?f=failed";
    if (view !== null && view !== "waiting" && view !== "mine" && view !== "long_wait") return null;
    // «waiting on me» (the list's default) is the Decide lens, with the item the link had open
    const item = params.get("item") ?? "";
    return ITEM.test(item) ? `/app/new/decide/${item}` : "/app/new/decide";
  }
  if (path === "/app/galaxy") {
    const focus = /^(?:res:|r#?)?([1-9]\d{0,8})$/i.exec(params.get("focus") ?? "");
    return focus ? `/app/new/world?sel=${focus[1]}` : "/app/new/world";
  }
  return null;
}

/** A classic issue-list address (/app/issues?view=all&status=…&severity=…&q=…&sort=…) as the address of NewUI's
 *  «all items» table (its own parameters: st / status / sev / q / sort — newui/lib/items reads them, and
 *  `__tests__/newuiItems.test.ts` checks the two agree). What the table cannot say is dropped. */
function itemsAddress(p: URLSearchParams): string {
  const status = p.get("status"), sev = p.get("severity"), sort = p.get("sort"), q = (p.get("q") ?? "").trim().slice(0, 200);
  const out = new URLSearchParams();
  // the classic list's default — no status in its address, which it never writes out — is EVERY status; only
  // «active» is the open ones (N27, review: it landed on «open», and a resolved match was shown there, not here)
  if (status !== "active") out.set("st", "all");
  if (status === "resolved" || status === "dismissed") out.set("status", status);
  if (sev && ["critical", "high", "medium", "low"].includes(sev)) out.set("sev", sev);
  if (q) out.set("q", q);
  if (sort === "oldest" || sort === "severity") out.set("sort", sort);
  const s = out.toString();
  return s ? `/app/new/items?${s}` : "/app/new/items";
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
