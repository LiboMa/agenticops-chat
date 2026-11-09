import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { cronSummary, runState } from "@/lib/scheduleRows";
import type { ScheduleLastExecution } from "@/api/types";

const tEn = (k: string) => (en as Record<string, string>)[k] ?? k;
const tZh = (k: string) => (zh as Record<string, string>)[k] ?? k;
const last = (status: string, over: Partial<ScheduleLastExecution> = {}): ScheduleLastExecution => ({
  id: 1, status, started_at: "2026-11-08T13:38:00", completed_at: null, duration_ms: null, error_summary: null, ...over,
});

describe("runState — the real latest run, never inferred from the switch (MVP-2.8.0 S1)", () => {
  it("never ran when there is no execution", () => {
    expect(runState(null).kind).toBe("never_run");
  });
  it("maps the execution status", () => {
    expect(runState(last("running")).kind).toBe("running");
    expect(runState(last("retrying")).kind).toBe("retrying");
    expect(runState(last("completed")).kind).toBe("succeeded");
    expect(runState(last("succeeded")).kind).toBe("succeeded");
    expect(runState(last("failed", { error_summary: "timeout" })).kind).toBe("failed");
  });
  it("keeps an unknown status as it is instead of guessing", () => {
    const s = runState(last("paused"));
    expect(s.kind).toBe("other");
    expect(s.raw).toBe("paused");
  });
});

describe("cronSummary — a cron expression in words", () => {
  it("says the common shapes in English", () => {
    expect(cronSummary("@once", tEn)).toBe("One-off");
    expect(cronSummary("*/10 * * * *", tEn)).toBe("Every 10 minutes");
    expect(cronSummary("0 * * * *", tEn)).toBe("Hourly at :00");
    expect(cronSummary("30 2 * * *", tEn)).toBe("Daily at 02:30");
  });
  it("says them in Chinese", () => {
    expect(cronSummary("@once", tZh)).toBe("一次性");
    expect(cronSummary("*/10 * * * *", tZh)).toBe("每 10 分钟");
    expect(cronSummary("0 * * * *", tZh)).toBe("每小时第 00 分");
    expect(cronSummary("30 2 * * *", tZh)).toBe("每天 02:30");
  });
  it("names no weekday: the scheduler reads cron's day-of-week off by one today (Mon=0), so any weekday sentence could be wrong", () => {
    expect(cronSummary("0 9 * * 1", tEn)).toBeNull();
    expect(cronSummary("0 0 * * 1", tZh)).toBeNull();
  });
  it("returns null for a shape it does not read, so the page shows only the expression", () => {
    expect(cronSummary("0 9 1-7 * 1", tEn)).toBeNull();
    expect(cronSummary("0 */2 * * *", tEn)).toBeNull();
    expect(cronSummary("garbage", tEn)).toBeNull();
  });
});
