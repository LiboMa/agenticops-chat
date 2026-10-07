import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { scheduleAt } from "@/lib/recheck";

describe("scheduleAt (C1(c) round 2): one timer to the moment the grace ends", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(Date.parse("2026-10-05T10:00:00Z")); });
  afterEach(() => vi.useRealTimers());

  it("fires once, at the moment, even though nothing else re-renders the page", () => {
    const fn = vi.fn();
    scheduleAt(Date.now() + 30_000, fn);
    vi.advanceTimersByTime(29_999);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(60_000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
  it("a moment already past fires at once", () => {
    const fn = vi.fn();
    scheduleAt(Date.now() - 5_000, fn);
    vi.advanceTimersByTime(0);
    expect(fn).toHaveBeenCalledTimes(1);
  });
  it("cancelling (unmount, or a new moment) stops it", () => {
    const fn = vi.fn();
    const cancel = scheduleAt(Date.now() + 30_000, fn);
    cancel();
    vi.advanceTimersByTime(60_000);
    expect(fn).not.toHaveBeenCalled();
  });
});
