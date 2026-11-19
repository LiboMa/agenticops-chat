/**
 * The Resources table (MVP-2.7.0 S4): filters and page in the URL, the account from the top bar's scope, health
 * from the server (graph health overlay) — a resource with no open issue is "unknown", never "healthy". Pure.
 */
import type { Resource, Schedule } from "@/api/types";
import type { StatusTone } from "@/components/ui/StatusText";
import { runState, type RunState } from "@/lib/scheduleRows";
import { agoParts } from "@/lib/sessionList";

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

// ── MVP-2.9.0 N24 (the 2.8.0 spec's S7): why a row's health reads as it does ───────────────────────────────────

const HEALTH_TONE: Record<string, StatusTone> = { critical: "danger", warning: "warn", notice: "info" };
const REASON_TONE: Record<string, StatusTone> = { no_open_issue: "neutral", stale: "warn", never_observed: "warn", absent: "neutral" };

export interface HealthView {
  /** the words: an open issue's level, else the reason there is none to report */
  key: string;
  tone: StatusTone;
  /** stale data says when the row was last observed */
  ago: { key: string; n: number } | null;
  issues: number;
}

/** What the health cell says. Never «healthy», and never a bare «unknown»: a row with no open issue says «no known
 *  issue», stale data says since when, a row never observed or gone says that. The reason is the server's
 *  (`health_reason`); a row without one — an older server — is read from its health alone. */
export function healthView(r: Pick<Resource, "health" | "health_reason" | "open_issues" | "observed_at">, now: number = Date.now()): HealthView {
  const issues = r.open_issues ?? 0;
  const level = r.health && r.health in HEALTH_TONE ? r.health : null;   // a level is only ever an open issue's
  if (level) {
    return { key: `resources.health.${level}`, tone: HEALTH_TONE[level], ago: null, issues };
  }
  const reason = r.health_reason && r.health_reason in REASON_TONE ? r.health_reason : "no_open_issue";
  return { key: `resources.reason.${reason}`, tone: REASON_TONE[reason],
           ago: reason === "stale" && r.observed_at ? agoParts(r.observed_at, now) : null, issues: 0 };
}

/** The page's «last resource scan» line: the newest run among the resource-scan schedules (pipeline `ResourceScan`)
 *  — its real state and when it ended (a run in flight: when it began). `null` until the schedules are known;
 *  `scheduleId: null` when there is no such schedule at all. */
export type ScanLine = { scheduleId: null } | { scheduleId: number; run: RunState; at: string | null; enabled: boolean };

export function scanLine(schedules: Pick<Schedule, "id" | "pipeline_name" | "is_enabled" | "last_execution">[] | undefined): ScanLine | null {
  if (!schedules) return null;
  const scans = schedules.filter((s) => s.pipeline_name === "ResourceScan");
  if (scans.length === 0) return { scheduleId: null };
  const started = (s: (typeof scans)[number]) => s.last_execution?.started_at ?? "";
  const newest = scans.reduce((a, b) => (started(b) > started(a) ? b : a));
  const last = newest.last_execution ?? null;
  return { scheduleId: newest.id, run: runState(last), at: last ? last.completed_at ?? last.started_at : null, enabled: newest.is_enabled };
}
