/**
 * The Agent metrics page (MVP-2.9.0 N24 — the 2.8.0 spec's S7): ONE range for the page, in the address, that every
 * module follows; a module may keep a range of its own only where the page's cannot say it, and then says so in its
 * title. A rate is never shown without what it was counted from; a cost is shown at a readable precision. Pure.
 */
export const RANGE_DAYS = [7, 30, 90] as const;
export type RangeDays = (typeof RANGE_DAYS)[number];
export const DEFAULT_DAYS: RangeDays = 30;

/** The cost module's own views (by month, by year) and the token modules' own short windows. */
export const COST_OWN = ["month", "year"] as const;
export const TOKENS_OWN = ["1h", "6h", "24h"] as const;
export type CostOwn = (typeof COST_OWN)[number];
export type TokensOwn = (typeof TOKENS_OWN)[number];

export interface MetricsQuery { days: RangeDays; cost: CostOwn | null; tokens: TokensOwn | null }

const pick = <T extends string>(all: readonly T[], value: string | null): T | null => all.find((v) => v === value) ?? null;

export function metricsQuery(params: URLSearchParams): MetricsQuery {
  const days = RANGE_DAYS.find((d) => String(d) === params.get("days")) ?? DEFAULT_DAYS;
  return { days, cost: pick(COST_OWN, params.get("cost")), tokens: pick(TOKENS_OWN, params.get("tokens")) };
}

/** The address with part of the query changed; defaults (30 days, a module that follows) leave it. */
export function metricsSearch(params: URLSearchParams, patch: Partial<MetricsQuery>): URLSearchParams {
  const next = new URLSearchParams(params);
  const q = { ...metricsQuery(params), ...patch };
  const set = (key: string, value: string | null) => { if (value) next.set(key, value); else next.delete(key); };
  set("days", q.days === DEFAULT_DAYS ? null : String(q.days));
  set("cost", q.cost);
  set("tokens", q.tokens);
  return next;
}

/** `GET /api/cost/summary?period=` */
export const costPeriod = (q: MetricsQuery): string => q.cost ?? (String(q.days) + "d");

/** `GET /api/agent-logs/summary?hours=` */
export const tokenHours = (q: MetricsQuery): number => (q.tokens ? Number(q.tokens.slice(0, -1)) : q.days * 24);

export type MetricsModule = "cost" | "tokens" | "location";

/** A module's range in words (a locale key and its number); `own` = it does not follow the page's range. */
export function rangeLabel(q: MetricsQuery, module: MetricsModule): { key: string; n: number; own: boolean } {
  if (module === "cost" && q.cost) return { key: "metrics.range." + q.cost, n: q.cost === "month" ? 12 : 3, own: true };
  if (module === "tokens" && q.tokens) return { key: "metrics.range.hours", n: tokenHours(q), own: true };
  return { key: "metrics.range.days", n: q.days, own: false };
}

/** Under this many judged RCAs the rate is said to rest on a small sample. */
export const SMALL_SAMPLE = 20;

export interface AccuracyView { correct: number; judged: number; rcas: number; small: boolean; none: boolean }

/** «2 / 2 judged correct», «2 / 15 RCAs judged» — the counts behind the top-1 rate, so «100 %» cannot be read as
 *  the accuracy of every RCA. `none` = nothing was judged (said as that, never as 0 %). Null without the counts. */
export function accuracyView(s: { correct?: number; judged?: number; rcas?: number } | undefined): AccuracyView | null {
  if (!s || typeof s.correct !== "number" || typeof s.judged !== "number" || typeof s.rcas !== "number") return null;
  return { correct: s.correct, judged: s.judged, rcas: s.rcas, small: s.judged > 0 && s.judged < SMALL_SAMPLE, none: s.judged === 0 };
}

const usable = (usd: number) => typeof usd === "number" && Number.isFinite(usd) && usd >= 0;

/** `$12.3` — about three figures; the exact figure belongs in a tooltip (`costExact`). */
export function costLabel(usd: number): string {
  if (!usable(usd)) return "—";
  if (usd === 0) return "$0";
  if (usd < 0.01) return "<$0.01";
  if (usd < 9.995) return "$" + usd.toFixed(2);
  if (usd < 99.95) return "$" + usd.toFixed(1);
  return "$" + Math.round(usd).toLocaleString("en-US");
}

/** The figure as recorded, to six decimals at most. */
export function costExact(usd: number): string {
  return usable(usd) ? "$" + String(Number(usd.toFixed(6))) : "—";
}
