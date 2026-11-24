import type { ScheduleLastExecution } from "@/api/types";
import { parseCronFields } from "@/lib/cronHelpers";

/** A schedule's latest REAL run (MVP-2.8.0 S1) — from its newest schedule_executions row, never from is_enabled or
 *  last_run_at. No row = never ran. A status this page does not know is kept as it is (`other` + `raw`). */
export type RunKind = "running" | "retrying" | "succeeded" | "failed" | "never_run" | "other";

export interface RunState {
  kind: RunKind;
  /** the stored status, for `other` */
  raw?: string;
}

const KINDS: Record<string, RunKind> = {
  running: "running", retrying: "retrying", completed: "succeeded", succeeded: "succeeded", failed: "failed",
};

export function runState(last: Pick<ScheduleLastExecution, "status"> | null | undefined): RunState {
  if (!last) return { kind: "never_run" };
  const kind = KINDS[last.status];
  return kind ? { kind } : { kind: "other", raw: last.status };
}

const pad = (v: string) => v.padStart(2, "0");
const isNum = (v: string) => /^\d{1,2}$/.test(v);

/** A cron expression in words for the common shapes (every N minutes, hourly, daily, one-off); null for
 *  anything else — the page then shows only the expression, never a wrong sentence. Times are the scheduler's (UTC). */
export function cronSummary(expr: string, t: (k: string) => string): string | null {
  if (expr.trim() === "@once") return t("schedules.cron.once");
  const f = parseCronFields(expr);
  if (!f || f.dom !== "*" || f.month !== "*") return null;
  const { minute, hour, dow } = f;
  if (/^\*\/\d+$/.test(minute) && hour === "*" && dow === "*") {
    return t("schedules.cron.everyMinutes").replace("{n}", minute.slice(2));
  }
  if (!isNum(minute)) return null;
  if (hour === "*" && dow === "*") return t("schedules.cron.hourly").replace("{m}", pad(minute));
  if (!isNum(hour)) return null;
  const time = `${pad(hour)}:${pad(minute)}`;
  if (dow === "*") return t("schedules.cron.daily").replace("{time}", time);
  // No weekday sentence: the scheduler matches cron's day-of-week against Python's weekday() (Monday = 0), so a
  // "* * 1" job runs on Tuesdays today — naming a day here could be wrong (owner's call to fix the scheduler).
  return null;
}
