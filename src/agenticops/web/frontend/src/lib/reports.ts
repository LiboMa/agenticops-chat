/**
 * The Reports pages' logic (MVP-2.9.0 N21 — the 2.8.0 spec's S4): the list's search and dates in the address, the
 * request for one page, the two counts, and what the coverage card says. Pure, so node can test it.
 */
import type { ReportCoverage } from "@/api/types";

export const REPORTS_PAGE = 50;

export interface ReportsQuery {
  q: string;
  /** UTC days, YYYY-MM-DD, both included; "" = no bound */
  from: string;
  to: string;
}

const utcDay = (value: string | null): string => {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const at = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(at.getTime()) && at.toISOString().slice(0, 10) === value ? value : "";
};

/** The list's query from the address (`q`, `from`, `to`); what cannot be read is no filter. */
export function reportsQuery(params: URLSearchParams): ReportsQuery {
  return { q: (params.get("q") ?? "").slice(0, 200), from: utcDay(params.get("from")), to: utcDay(params.get("to")) };
}

/** The address for a query: only what is set, the page's other parameters kept. */
export function reportsSearch(current: URLSearchParams, q: ReportsQuery): string {
  const next = new URLSearchParams(current);
  for (const key of ["q", "from", "to"]) next.delete(key);
  if (q.q.trim()) next.set("q", q.q.trim());
  if (q.from) next.set("from", q.from);
  if (q.to) next.set("to", q.to);
  return next.toString();
}

/** The request for one page (apiFetch path). */
export function reportsRequest(q: ReportsQuery, offset: number): string {
  const params = new URLSearchParams({ limit: String(REPORTS_PAGE), offset: String(offset) });
  if (q.q.trim()) params.set("q", q.q.trim());
  if (q.from) params.set("date_from", q.from);
  if (q.to) params.set("date_to", q.to);
  return `/reports?${params.toString()}`;
}

/** Where the next page starts, or undefined when everything is listed (or the last page came back empty). */
export function nextOffset(loaded: number, total: number, lastPage: number = 1): number | undefined {
  return lastPage > 0 && loaded < total ? loaded : undefined;
}

export const isFiltered = (q: ReportsQuery): boolean => Boolean(q.q.trim() || q.from || q.to);

/** «matched X» and «Z in all» are two numbers, never one sentence: `matched` only when a search or a date is set. */
export function countsView(q: ReportsQuery, total: number, allTotal: number): { matched: number | null; all: number } {
  return { matched: isFiltered(q) ? total : null, all: allTotal };
}

export interface CoverageView {
  tone: "ok" | "warn";
  stateKey: "reports.coverage.complete" | "reports.coverage.partial";
  accounts: string[];
  regions: string[];
  readAt: string;
  /** each kind of gap that happened, with its count */
  partial: { key: string; n: number }[];
}

const GAPS = ["truncated", "offloaded", "failed"] as const;

/** What the coverage card says — from the record alone (the sentences are the page's templates, so the two
 *  languages cannot differ). null = no card: the report has no record, or one this page cannot read. The counts
 *  decide «partial», whatever the record calls itself. */
export function coverageView(c: ReportCoverage | null | undefined): CoverageView | null {
  if (!c || !Array.isArray(c.accounts) || !Array.isArray(c.regions) || !c.partial || typeof c.partial !== "object") return null;
  const partial = GAPS.map((k) => ({ key: `reports.coverage.${k}`, n: Number(c.partial[k]) || 0 })).filter((p) => p.n > 0);
  const gaps = partial.length > 0 || c.completeness === "partial";
  return { tone: gaps ? "warn" : "ok", stateKey: gaps ? "reports.coverage.partial" : "reports.coverage.complete",
           accounts: c.accounts, regions: c.regions, readAt: c.read_at, partial };
}
