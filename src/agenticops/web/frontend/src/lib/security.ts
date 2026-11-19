/**
 * The Security page's logic (MVP-2.9.0 N20 — the 2.8.0 spec's S3): what an account's card says, the trend as chart
 * rows, which account the radar draws, and the findings list's filters in the address. Pure, so node can test it.
 */
import type { SecurityAccountScore, SecurityTrend } from "@/api/types";

// ── the score ─────────────────────────────────────────────────────────────────────────────────────────────────

export type Tier = "good" | "watch" | "priority";

/** ≥ 80 good · 50–80 worth attention · < 50 check first. */
export function scoreTier(score: number): Tier {
  return score >= 80 ? "good" : score >= 50 ? "watch" : "priority";
}

export const TIER_TONE = { good: "ok", watch: "warn", priority: "danger" } as const;

export interface CardView {
  /** scored: every source was read (or it was not recorded); partial: scored, some sources failed; unscored: none could be read */
  state: "scored" | "partial" | "unscored";
  score: string | null;
  tier: Tier | null;
  errors: { source: string; error: string }[];
}

/** An account's card. No score → no number and no tier: an account nobody could read is neither 0 nor 100. */
export function cardView(a: SecurityAccountScore): CardView {
  if (a.overall_score === null) return { state: "unscored", score: null, tier: null, errors: a.collection_errors };
  return { state: a.collection === "partial" ? "partial" : "scored", score: a.overall_score.toFixed(1),
           tier: scoreTier(a.overall_score), errors: a.collection_errors };
}

// ── the trend ─────────────────────────────────────────────────────────────────────────────────────────────────

const RANGES = [7, 30, 90] as const;
export type TrendDays = (typeof RANGES)[number];
export const TREND_RANGES: readonly TrendDays[] = RANGES;

export function trendDays(params: URLSearchParams): TrendDays {
  const n = Number(params.get("days"));
  return RANGES.find((r) => r === n) ?? 30;
}

// the first account is a solid line; each later one is dashed its own way (colour is not the only difference:
// colour-blind readers and print)
const DASHES: (string | undefined)[] = [undefined, "6 4", "2 4", "10 3 2 3"];

export interface TrendChart {
  /** one row per UTC day of the window, oldest first: `day` + one `a<k>` per account (null = no score that day) */
  rows: Array<{ day: string } & Record<string, number | string | null>>;
  series: { key: string; name: string; dash: string | undefined; points: number }[];
  /** day → the accounts whose score that day came from a partly read account */
  partial: Record<string, string[]>;
}

/** `today` is a UTC day key (YYYY-MM-DD). The window is today and the `days - 1` before it — the server's. */
export function trendChart(trend: SecurityTrend, today: string): TrendChart {
  const end = new Date(`${today}T00:00:00Z`).getTime();
  const days = Array.from({ length: trend.days }, (_, i) => new Date(end - (trend.days - 1 - i) * 86_400_000).toISOString().slice(0, 10));
  const inWindow = new Set(days);
  const partial: Record<string, string[]> = {};
  const byAccount = trend.accounts.map((a) => {
    const at = new Map<string, number>();
    for (const p of a.points) {
      if (!inWindow.has(p.day)) continue;
      at.set(p.day, p.score);
      if (p.partial) (partial[p.day] ??= []).push(a.account_name);
    }
    return at;
  });
  const rows = days.map((day) => {
    const row: { day: string } & Record<string, number | string | null> = { day };
    byAccount.forEach((at, k) => { row[`a${k}`] = at.get(day) ?? null; });
    return row;
  });
  const series = trend.accounts.map((a, k) => ({ key: `a${k}`, name: a.account_name, dash: DASHES[k % DASHES.length], points: byAccount[k].size }));
  return { rows, series, partial };
}

// ── the radar ─────────────────────────────────────────────────────────────────────────────────────────────────

/** Which account the radar draws: the top bar's account when one is chosen (null when it has no snapshot); under
 *  «all», the one picked on the page, else the first. The pick filters nothing else. */
export function radarAccount(accounts: SecurityAccountScore[], scope: number | null, picked: string | null): SecurityAccountScore | null {
  if (scope !== null) return accounts.find((a) => a.account_id === scope) ?? null;
  return accounts.find((a) => a.account_name === picked) ?? accounts[0] ?? null;
}

/** The radar's points, by category name. A category nobody could read sits at the centre and is marked — the
 *  chart needs a number, the label says it is not one. */
export function radarRows(a: SecurityAccountScore): { category: string; score: number; collected: boolean }[] {
  return Object.keys(a.category_scores).sort().map((category) => {
    const value = a.category_scores[category];
    return { category, score: value ?? 0, collected: value !== null && value !== undefined };
  });
}

// ── the findings list ─────────────────────────────────────────────────────────────────────────────────────────

export const FINDINGS_PAGE = 20;
export const SEVERITY_CHOICES = ["critical", "high", "medium", "low"] as const;
export const REACH_CHOICES = ["reachable", "undetermined", "not_reachable"] as const;

export interface FindingsQuery {
  /** one severity, or "" for any */
  severity: string;
  status: "open" | "all";
  /** one reachability state, or "" for any */
  reach: string;
  q: string;
  page: number;
}

const oneOf = (value: string | null, choices: readonly string[]): string => (value !== null && choices.includes(value) ? value : "");

/** The list's filters from the address (`sev`, `st`, `reach`, `q`, `p`); anything unreadable is the default. */
export function findingsQuery(params: URLSearchParams): FindingsQuery {
  const page = Number(params.get("p"));
  return {
    severity: oneOf(params.get("sev"), SEVERITY_CHOICES),
    status: params.get("st") === "all" ? "all" : "open",
    reach: oneOf(params.get("reach"), REACH_CHOICES),
    q: (params.get("q") ?? "").slice(0, 200),
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

/** The address for these filters: only what differs from the default, the page's other parameters kept. */
export function findingsSearch(current: URLSearchParams, q: FindingsQuery): string {
  const next = new URLSearchParams(current);
  for (const key of ["sev", "st", "reach", "q", "p"]) next.delete(key);
  if (q.severity) next.set("sev", q.severity);
  if (q.status === "all") next.set("st", "all");
  if (q.reach) next.set("reach", q.reach);
  if (q.q.trim()) next.set("q", q.q.trim());
  if (q.page > 1) next.set("p", String(q.page));
  return next.toString();
}

/** The request for one page (apiFetch path). `accountId` undefined = all accounts. */
export function findingsRequest(q: FindingsQuery, accountId: number | undefined): string {
  const params = new URLSearchParams({ status: q.status, limit: String(FINDINGS_PAGE), offset: String((q.page - 1) * FINDINGS_PAGE) });
  if (accountId !== undefined) params.set("account_id", String(accountId));
  if (q.severity) params.set("severity", q.severity);
  if (q.reach) params.set("reachability", q.reach);
  if (q.q.trim()) params.set("q", q.q.trim());
  return `/security/findings?${params.toString()}`;
}

/** «showing from–to of total», and how many pages there are; a page past the end is the last one. */
export function pageInfo(total: number, page: number): { from: number; to: number; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(total / FINDINGS_PAGE));
  const at = Math.min(Math.max(1, page), pages);
  if (total === 0) return { from: 0, to: 0, page: 1, pages: 1 };
  return { from: (at - 1) * FINDINGS_PAGE + 1, to: Math.min(total, at * FINDINGS_PAGE), page: at, pages };
}
