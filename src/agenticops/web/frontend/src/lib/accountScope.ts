/**
 * The top bar's account scope (MVP-2.7.0 S4): one account (or All) that the work lists follow — the Cases queue,
 * the Plans & changes Fix and Changes tabs, Resources and «Needs your attention». Stored per user in this browser.
 * A detail page shows its own record's account, so the scope is locked there; pages it does not filter
 * (overview, security, Galaxy, …) say so. Pure, so node can test it.
 */
import { userKey } from "@/lib/home";

export type ScopeMode = "active" | "locked" | "notApplied";

const BASE = "aiops-account-scope";
export const scopeKey = (userId: number | null | undefined) => userKey(BASE, userId);

const asId = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && /^\d+$/.test(v) ? Number(v) : NaN;
  return Number.isInteger(n) && n > 0 ? n : null;
};

/** The stored scope if it is still an account; null (All) otherwise. While the list is loading a well-formed id
 *  is kept, so a reload does not flash All and reset the user's choice; when the list failed to load the scope is
 *  All — an id nobody can check must not filter (and empty) every list. */
export function validScope(stored: unknown, accounts: { id: number }[] | undefined, failed = false): number | null {
  const id = asId(stored);
  if (failed) return null;
  if (id == null || !accounts) return id;
  return accounts.some((a) => a.id === id) ? id : null;
}

const LISTS = new Set(["/app/issues", "/app/plans", "/app/changes", "/app/resources"]);

/** active: the lists, and the Cases split view (its queue stays on screen); locked: a detail page — and a case
 *  opened full screen on a narrow screen; notApplied: everything else. */
export function scopeMode(pathname: string, wide: boolean): ScopeMode {
  const path = pathname.replace(/\/+$/, "");
  if (LISTS.has(path)) return "active";
  const m = /^\/app\/(issues|plans|changes|resources)\/[^/]+$/.exec(path);
  if (!m) return "notApplied";
  return m[1] === "issues" && wide ? "active" : "locked";
}

/** An old link's own account filter (`?account=` on fix plans, `?account_id=` on changes) → the scope, once; the
 *  parameter leaves the URL either way. null when the link carries none. */
export function adoptAccountParam(search: string): { accountId: number | null; search: string } | null {
  const params = new URLSearchParams(search);
  const raw = params.get("account") ?? params.get("account_id");
  if (raw == null) return null;
  params.delete("account");
  params.delete("account_id");
  const rest = params.toString();
  return { accountId: asId(raw), search: rest ? `?${rest}` : "" };
}
