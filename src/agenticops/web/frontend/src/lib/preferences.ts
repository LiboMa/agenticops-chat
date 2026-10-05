import { ApiError, apiFetch, getAuthToken } from "@/api/client";
import { queryClient } from "@/queryClient";
import { bootstrapKey, type UiBootstrap, type UiPreferences } from "@/hooks/useBootstrap";
import { allowedRoute, currentUserId, userKey } from "@/lib/home";

type Changes = Partial<Omit<UiPreferences, "revision">>;

// One write at a time per tab: each names the revision the previous one produced, so a tab never trips over
// its own 412. Another tab's write is a real 412: re-read once and replay these changes on top.
let queue: Promise<unknown> = Promise.resolve();

function patch(changes: Changes, ifMatch: string) {
  return apiFetch<UiPreferences>("/users/me/preferences", {
    method: "PATCH", headers: { "If-Match": ifMatch }, body: JSON.stringify(changes),
  });
}

export function savePreferences(changes: Changes, opts: { wildcard?: boolean } = {}): Promise<UiPreferences | null> {
  const run = queue.then(async () => {
    const key = bootstrapKey();
    const boot = queryClient.getQueryData<UiBootstrap>(key);
    if (!boot) return null;
    queryClient.setQueryData<UiBootstrap>(key, { ...boot, preferences: { ...boot.preferences, ...changes } });
    let doc: UiPreferences;
    try {
      doc = await patch(changes, opts.wildcard ? "*" : `"${boot.preferences.revision}"`);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 412)) throw e;
      const fresh = await apiFetch<UiPreferences>("/users/me/preferences");
      doc = await patch(changes, `"${fresh.revision}"`);
    }
    queryClient.setQueryData<UiBootstrap>(key, (b) => (b ? { ...b, preferences: doc } : b));
    return doc;
  });
  queue = run.catch(() => undefined);
  return run.catch(() => {
    queryClient.invalidateQueries({ queryKey: bootstrapKey() });
    return null;
  });
}

// ── the last place, for "resume" ────────────────────────────────────────────
// This browser's copy is written at once (per user); the server's at most every 30 s, only when it changed,
// and once more as the page goes away — navigation never floods the preferences endpoint.
const LAST_ROUTE = "aiops-last-route";
const SERVER_EVERY_MS = 30_000;
let sent: string | null = null;
let sentAt = 0;
let pending: string | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

export function localLastRoute(): string | null {
  const v = localStorage.getItem(userKey(LAST_ROUTE, currentUserId()));
  return allowedRoute(v) ? v : null;
}

function flush() {
  timer = null;
  if (pending === null || pending === sent) return;
  sent = pending;
  sentAt = Date.now();
  void savePreferences({ last_route: pending }, { wildcard: true });
}

export function recordLastRoute(path: string): void {
  if (!allowedRoute(path)) return;
  localStorage.setItem(userKey(LAST_ROUTE, currentUserId()), path);
  pending = path;
  const wait = sentAt + SERVER_EVERY_MS - Date.now();
  if (wait <= 0) flush();
  else if (!timer) timer = setTimeout(flush, wait);
}

export function forgetLastRoute(): void {
  localStorage.removeItem(userKey(LAST_ROUTE, currentUserId()));
  pending = null;
  if (sent !== null) {
    sent = null;
    void savePreferences({ last_route: null }, { wildcard: true });
  }
}

/** The page is going away: hand the unsent last place to the browser to deliver (keepalive). */
export function flushOnPageHide(): void {
  const token = getAuthToken();
  if (!token || pending === null || pending === sent) return;
  sent = pending;
  void fetch("/api/users/me/preferences", {
    method: "PATCH", keepalive: true,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "If-Match": "*" },
    body: JSON.stringify({ last_route: pending }),
  }).catch(() => undefined);
}
