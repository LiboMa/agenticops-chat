/**
 * The Cases page (MVP-2.7.0 S4): a queue beside the reading pane at ≥ 1280px, one or the other below. Every filter
 * lives in the URL and runs on the server (GET /api/health-issues); a case link keeps the query, so selecting a case
 * keeps the filters. Pure, so node can test it.
 */
import type { IssueStatus } from "@/api/types";
import type { HealthIssueFilters } from "@/hooks/useHealthIssues";
import { ISSUE_STATUSES } from "@/lib/issueStatus";
import { resolveIssueScope } from "@/lib/issueScope";

export const SPLIT_MIN_WIDTH = 1280;
export const SPLIT_MEDIA = `(min-width: ${SPLIT_MIN_WIDTH}px)`;
export const QUEUE_CAP = 200;

// The auto-pipeline moves an issue out of literal "open" within seconds: active = anything not yet closed
export const ACTIVE_STATUSES: readonly IssueStatus[] = ISSUE_STATUSES.filter((s) => s !== "resolved" && s !== "dismissed");
export const STATUS_GROUPS = ["all", "active", "resolved", "dismissed"] as const;
export const SEVERITY_CHOICES = ["critical", "high", "medium", "low"] as const;
export const SORTS = ["newest", "oldest", "severity"] as const;
/** The queue's quick views (MVP-2.8.0): «在等我» (the to-do workbench, merged in — issues AND changes waiting on you,
 *  grouped by decision; GET /api/ui/attention) first, then the issue list: all, failed, waiting long. */
export const QUICK_VIEWS = ["waiting", "all", "failed", "long_wait"] as const;
export type QuickView = (typeof QUICK_VIEWS)[number];
type Sort = (typeof SORTS)[number];

const DEFAULTS: Record<string, string> = { scope: "ops", sort: "newest", status: "all", view: "waiting" };

/** Where «问题» opens: on what waits on you — a viewer, who can act on nothing, on the whole list. */
export const defaultView = (readOnly: boolean): QuickView => (readOnly ? "all" : "waiting");

/** The view in the URL; none (or an unknown one) is the default; the old «待我处理» (`mine`) is «在等我». */
export function currentView(params: URLSearchParams, readOnly: boolean): QuickView {
  const v = params.get("view");
  if (v === "mine") return "waiting";
  return v && (QUICK_VIEWS as readonly string[]).includes(v) ? (v as QuickView) : defaultView(readOnly);
}

export function queueFilters(params: URLSearchParams): HealthIssueFilters & { limit: number } {
  const status = params.get("status");
  const severity = params.get("severity");
  const sort = params.get("sort");
  const q = params.get("q")?.trim();
  const view = params.get("view");
  return {
    scope: resolveIssueScope(params.get("scope")),
    ...(status === "active" ? { status: ACTIVE_STATUSES.join(",") }
      : status === "resolved" || status === "dismissed" ? { status } : {}),
    ...(severity && (SEVERITY_CHOICES as readonly string[]).includes(severity) ? { severity } : {}),
    ...(q ? { q: q.slice(0, 200) } : {}),
    sort: sort && (SORTS as readonly string[]).includes(sort) ? (sort as Sort) : "newest",
    // only these two filter the issue list (subsets of the to-do rows, server side); «在等我» is not this list at all
    ...(view === "failed" || view === "long_wait" ? { view } : {}),
    limit: QUEUE_CAP + 1,
  };
}

/** The params with one filter set; a default or empty value leaves the URL (`defaults` overrides — a viewer's default
 *  view is «全部»). Changing the view drops the selected «在等我» item. */
export function queueParams(params: URLSearchParams, key: string, value: string,
                            defaults: Partial<Record<string, string>> = {}): URLSearchParams {
  const next = new URLSearchParams(params);
  if (!value || ({ ...DEFAULTS, ...defaults })[key] === value) next.delete(key);
  else next.set(key, value);
  if (key === "view") next.delete("item");
  return next;
}

/** A «在等我» row's search: the same view and search, this item selected (none: back to the list). */
export function waitingSearch(params: URLSearchParams, item: string | null): string {
  const next = new URLSearchParams(params);
  if (item) next.set("item", item);
  else next.delete("item");
  const qs = next.toString();
  return qs ? `?${qs}` : "";
}

export const caseHref = (id: number, search: string) => `/app/issues/${id}${search}`;

/** sessionStorage key for the list's scroll position under one set of filters (order-insensitive). */
export function scrollKey(search: string): string {
  const params = [...new URLSearchParams(search).entries()].sort(([a, x], [b, y]) => a.localeCompare(b) || x.localeCompare(y));
  return `aiops-cases-scroll:${new URLSearchParams(params).toString()}`;
}
export const LAST_CASE_KEY = "aiops-cases-last";

export type BackTarget = { kind: "history" } | { kind: "link"; to: string };

/** A case opened from the queue goes back through history (same filters, same scroll); a deep link goes to the
 *  list under the same query. */
export function backTarget(state: unknown, search: string): BackTarget {
  return (state as { fromQueue?: boolean } | null)?.fromQueue ? { kind: "history" } : { kind: "link", to: `/app/issues${search}` };
}

export const capped = (rows: readonly unknown[]) => rows.length > QUEUE_CAP;

/** The history state a queue row navigates with. Only the narrow list → full-screen hop is "from the queue": in the
 *  split view a selection is not something back should return through (a resize would make back walk old cases). */
export const rowState = (wide: boolean) => (wide ? undefined : { fromQueue: true });
