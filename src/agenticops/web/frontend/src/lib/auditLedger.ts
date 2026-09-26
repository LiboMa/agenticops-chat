import { ApiError } from "@/api/client";
import { parseApiDate } from "@/lib/formatDate";
import type { AuditLogEntry, PlanStats } from "@/api/types";

export type WorkKind = "fix" | "change";
export type KindFilter = "all" | WorkKind;

/** The work-item kind an audit row is a decision on, or null when it is not a plan/change decision.
 *  Mirrors plan_stats_service's classification (Plan B T12 r6 + r10), so the table and the header counts agree. */
export function decisionKind(
  row: Pick<AuditLogEntry, "action" | "entity_type" | "details">,
): WorkKind | null {
  // Legacy rows may hold a string in `details` (Task 1 R12); treat anything but a non-null object as {}.
  const d: Record<string, unknown> =
    row.details && typeof row.details === "object" ? (row.details as Record<string, unknown>) : {};
  const { action, entity_type } = row;
  if (action.startsWith("change.")) return "change";
  if (action.startsWith("plan.")) return d.plan_kind === "change" ? null : "fix";
  if (action.startsWith("authz.")) {
    if (entity_type === "change_request") return "change";
    if (entity_type === "fix_plan") return d.plan_kind === "change" ? "change" : "fix";
    const permission = String(d.permission ?? "");
    if (permission.startsWith("change.")) return "change";
    if (permission.startsWith("plan.")) return "fix";
    return null;
  }
  return null;
}

/** Merge the three ledger queries into one newest-first page. */
export function mergeDecisionRows(
  pages: readonly (readonly AuditLogEntry[] | undefined)[],
  kind: KindFilter,
  limit: number,
): { rows: AuditLogEntry[]; truncated: boolean } {
  const epoch = (r: AuditLogEntry) => parseApiDate(r.timestamp)?.getTime();

  // 1. Cutoff. A full page (length >= limit) may hide older rows; below the latest full page's oldest row only
  //    some sources are complete, so drop everything older than that boundary.
  let anyFull = false;
  let cutoff: number | null = null;
  for (const page of pages) {
    if (!page || page.length < limit) continue;
    anyFull = true;
    let oldest: number | null = null;
    for (const r of page) {
      const e = epoch(r);
      if (e === undefined) continue;
      if (oldest === null || e < oldest) oldest = e;
    }
    if (oldest !== null && (cutoff === null || oldest > cutoff)) cutoff = oldest;
  }

  const kept: AuditLogEntry[] = [];
  for (const page of pages) {
    if (!page) continue;
    for (const r of page) {
      if (cutoff !== null) {
        const e = epoch(r);
        if (e !== undefined && e < cutoff) continue;
      }
      kept.push(r);
    }
  }

  // 2. Dedupe by id.
  const byId = new Map<number, AuditLogEntry>();
  for (const r of kept) if (!byId.has(r.id)) byId.set(r.id, r);

  // 3. Filter to decisions of the wanted kind.
  const filtered: AuditLogEntry[] = [];
  for (const r of byId.values()) {
    const k = decisionKind(r);
    if (k === null) continue;
    if (kind !== "all" && k !== kind) continue;
    filtered.push(r);
  }

  // 4. Sort newest-first; unparseable timestamps sort last; ties break by id descending.
  filtered.sort((a, b) => {
    const ea = epoch(a) ?? 0;
    const eb = epoch(b) ?? 0;
    if (ea !== eb) return eb - ea;
    return b.id - a.id;
  });

  return { rows: filtered.slice(0, limit), truncated: anyFull || filtered.length > limit };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

function sortByBucket(rows: PlanStats["series"]): PlanStats["series"] {
  return [...rows].sort((a, b) => (a.bucket < b.bucket ? -1 : a.bucket > b.bucket ? 1 : 0));
}

/** One row per UTC day of the period, zeros where the server sent none. */
export function fillDailySeries(
  series: PlanStats["series"],
  start: string,
  end: string,
): PlanStats["series"] {
  const startDay = start.slice(0, 10);
  const endDay = end.slice(0, 10);
  const startDate = new Date(`${startDay}T00:00:00Z`);
  const endDate = new Date(`${endDay}T00:00:00Z`);
  const ok =
    DATE_RE.test(startDay) &&
    DATE_RE.test(endDay) &&
    !Number.isNaN(startDate.getTime()) &&
    !Number.isNaN(endDate.getTime()) &&
    startDate.getTime() <= endDate.getTime() &&
    (endDate.getTime() - startDate.getTime()) / DAY_MS <= 400;
  if (!ok) return sortByBucket(series);

  const byBucket = new Map(series.map((row) => [row.bucket, row]));
  const inRange = new Set<string>();
  const out: PlanStats["series"] = [];
  // UTC-only iteration: local time repeats or skips a day at a DST change.
  for (const d = new Date(startDate); d.getTime() <= endDate.getTime(); d.setUTCDate(d.getUTCDate() + 1)) {
    const day = d.toISOString().slice(0, 10);
    inRange.add(day);
    out.push(byBucket.get(day) ?? { bucket: day, created: 0, completed: 0, failed: 0 });
  }
  for (const row of series) if (!inRange.has(row.bucket)) out.push(row);
  return sortByBucket(out);
}

export function fmtSecs(s: number | null | undefined): string {
  if (s == null || Number.isNaN(s)) return "-";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export function fmtRate(r: number | null | undefined): string {
  if (r == null) return "-";
  return `${Math.round(r * 100)}%`;
}

/** A 401/403 from the audit gate: the section shows the admin-only notice instead of an error. */
export function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.status === 403);
}
