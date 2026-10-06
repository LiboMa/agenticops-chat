/** Where /app lands, where a login returns to, and what "resume" may reopen (MVP-2.7.0 S2).
 *  Precedence at /app: a pinned home > the last allow-listed place > Chat. An explicit URL is never redirected:
 *  only the bare /app consults preferences. */

export type Home = "resume" | "chat" | "issues" | "reports";

// Internal read routes only — the server keeps the same list (services/ui_preferences._ROUTES) and
// tests/fixtures/ui_last_route_cases.json pins both.
const ROUTES = [
  /^\/app\/(chat|issues|reports|changes|plans|resources|schedules|skills)(\/[A-Za-z0-9][A-Za-z0-9_-]{0,99})?$/,
  /^\/app\/(audit|overview|agent-metrics|galaxy|security|settings|signals)$/,
];

export function allowedRoute(route: unknown): route is string {
  return typeof route === "string" && route.length <= 1000 && ROUTES.some((re) => re.test(route));
}

const PINNED: Record<Exclude<Home, "resume">, string> = {
  chat: "/app/chat",
  issues: "/app/issues",
  reports: "/app/reports",
};

export function homeTarget(prefs: { home?: string } | null, lastRoute: string | null): string {
  const home = prefs?.home;
  if (home === "chat" || home === "issues" || home === "reports") return PINNED[home];
  return allowedRoute(lastRoute) ? lastRoute : "/app/chat";
}

/** A login's `next`: same origin, inside /app, not the login page — returned normalised, with its query and
 *  hash (an issue's phase lives in the hash). Anything else is null, and the caller lands on /app. */
export function safeNext(next: string | null | undefined, origin: string): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return null;
  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return null;
  }
  if (url.origin !== origin) return null;
  const inApp = url.pathname === "/app" || url.pathname.startsWith("/app/");
  if (!inApp || url.pathname === "/app/login" || url.pathname.startsWith("/app/login/")) return null;
  return url.pathname + url.search + url.hash;
}

/** The login page, carrying where the user was (the bare home and the login page itself are not carried). */
export function loginPath(loc: { pathname: string; search: string; hash: string }): string {
  if (loc.pathname === "/app" || loc.pathname === "/app/" || loc.pathname.startsWith("/app/login")) return "/app/login";
  return `/app/login?next=${encodeURIComponent(loc.pathname + loc.search + loc.hash)}`;
}

/** The objects "resume" checks before reopening, and the list it falls back to when one is gone. */
export function probeFor(route: string): { api: string; list: string } | null {
  const m = route.match(/^\/app\/(issues|changes|reports|chat|plans)\/([A-Za-z0-9][A-Za-z0-9_-]*)$/);
  if (!m) return null;
  const [, kind, id] = m;
  const api = { issues: `/health-issues/${id}`, changes: `/changes/${id}`, reports: `/reports/${id}`,
                chat: `/chat/sessions/${id}`, plans: `/fix-plans/${id}` }[kind]!;
  return { api, list: `/app/${kind}` };
}

/** A local storage key private to the signed-in user, so a shared browser never reopens someone else's place. */
export function userKey(base: string, userId: number | null | undefined): string {
  return `${base}:${userId ?? "anon"}`;
}

export function currentUserId(): number | null {
  try {
    const raw = localStorage.getItem("aiops_user");
    const id = raw ? JSON.parse(raw)?.user_id : null;
    return typeof id === "number" ? id : null;
  } catch {
    return null;
  }
}
