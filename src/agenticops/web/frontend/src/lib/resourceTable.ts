/**
 * The Resources table (MVP-2.7.0 S4): filters and page in the URL, the account from the top bar's scope, health
 * from the server (graph health overlay) — a resource with no open issue is "unknown", never "healthy". Pure.
 */
export const PAGE_SIZES = [50, 100, 200] as const;
const HEALTH = new Set(["unknown", "notice", "warning", "critical"]);
const DEFAULTS: Record<string, string> = { page: "1", size: "50" };

export interface ResourceTableFilters {
  type?: string; region?: string; search?: string;
  includeAbsent: boolean; limit: number; offset: number; page: number; size: number;
}

export function resourceFilters(params: URLSearchParams): ResourceTableFilters {
  const size = Number(params.get("size"));
  const pageRaw = params.get("page") ?? "";
  const page = /^\d+$/.test(pageRaw) && Number(pageRaw) >= 1 ? Number(pageRaw) : 1;
  const sz = (PAGE_SIZES as readonly number[]).includes(size) ? size : 50;
  const type = params.get("type") || undefined;
  const region = params.get("region") || undefined;
  const search = params.get("q")?.trim() || undefined;
  return {
    ...(type ? { type } : {}), ...(region ? { region } : {}), ...(search ? { search } : {}),
    includeAbsent: params.get("absent") === "1", limit: sz, offset: (page - 1) * sz, page, size: sz,
  };
}

/** The params with one filter set; any filter but the page itself goes back to page 1; defaults leave the URL. */
export function resourceParams(params: URLSearchParams, key: string, value: string): URLSearchParams {
  const next = new URLSearchParams(params);
  if (key !== "page") next.delete("page");
  if (!value || DEFAULTS[key] === value) next.delete(key);
  else next.set(key, value);
  return next;
}

export const healthKey = (health: string | null | undefined) =>
  `resources.health.${health && HEALTH.has(health) ? health : "unknown"}`;

export const lifecycleKey = (r: { absent_since?: string | null }) =>
  r.absent_since ? "resources.lifecycle.absent" : "resources.lifecycle.present";

export const resourceHref = (id: number) => `/app/resources/${id}`;
