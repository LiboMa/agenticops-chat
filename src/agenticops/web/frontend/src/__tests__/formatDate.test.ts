import { afterAll, beforeAll, describe, it, expect, vi } from "vitest";
import { formatElapsed, formatFullDate, formatShortDate, parseApiDate } from "@/lib/formatDate";

// A naive timestamp only misparses when the local zone is not UTC, so pin a +08:00 zone:
// these tests must also fail against a broken parser on a UTC machine.
beforeAll(() => {
  vi.stubEnv("TZ", "Asia/Shanghai");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

describe("parseApiDate", () => {
  it("reads an offset-less ISO datetime as UTC", () => {
    expect(parseApiDate("2026-09-26T08:05:00")?.toISOString()).toBe("2026-09-26T08:05:00.000Z");
  });
  it("handles microseconds, as SQLite returns them", () => {
    expect(parseApiDate("2026-09-26T08:05:00.123456")?.toISOString()).toBe("2026-09-26T08:05:00.123Z");
  });
  it("keeps an explicit offset", () => {
    expect(parseApiDate("2026-09-26T16:05:00+08:00")?.toISOString()).toBe("2026-09-26T08:05:00.000Z");
  });
  it("returns a valid Date as is", () => {
    const d = new Date(Date.UTC(2026, 8, 26, 8, 5));
    expect(parseApiDate(d)).toBe(d);
  });
  it("returns null for empty, null, unparseable or invalid input", () => {
    expect(parseApiDate("garbage")).toBeNull();
    expect(parseApiDate(null)).toBeNull();
    expect(parseApiDate(new Date(NaN))).toBeNull();
    expect(parseApiDate("")).toBeNull();
    expect(parseApiDate(undefined)).toBeNull();
  });
});

describe("formatShortDate / formatFullDate", () => {
  it("format a naive datetime identically to the same string with Z", () => {
    expect(formatShortDate("2026-09-26T08:05:00")).toBe(formatShortDate("2026-09-26T08:05:00Z"));
    expect(formatFullDate("2026-09-26T08:05:00")).toBe(formatFullDate("2026-09-26T08:05:00Z"));
    expect(formatShortDate("2026-09-26T08:05:00")).toBe("Sep 26, 08:05");
    expect(formatFullDate("2026-09-26T08:05:00")).toBe("Sep 26, 2026, 08:05:00");
  });
  it("format microseconds and an explicit offset", () => {
    expect(formatFullDate("2026-09-26T08:05:00.123456")).toBe("Sep 26, 2026, 08:05:00");
    expect(formatFullDate("2026-09-26T16:05:00+08:00")).toBe(formatFullDate("2026-09-26T08:05:00Z"));
  });
  it("leave a Date input unchanged", () => {
    const d = new Date(Date.UTC(2026, 8, 26, 8, 5, 7));
    expect(formatShortDate(d)).toBe("Sep 26, 08:05");
    expect(formatFullDate(d)).toBe("Sep 26, 2026, 08:05:07");
  });
  it('return "-" for empty, null and unparseable input', () => {
    for (const bad of ["", null, "garbage"]) {
      expect(formatShortDate(bad)).toBe("-");
      expect(formatFullDate(bad)).toBe("-");
    }
  });
});

describe("formatElapsed", () => {
  it("seconds, then minutes + seconds, then hours + minutes; negative or NaN reads 0s", () => {
    expect([0, 42_000, 185_000, 3_600_000 + 125_000].map(formatElapsed)).toEqual(["0s", "42s", "3m 05s", "1h 02m"]);
    expect(formatElapsed(-5_000)).toBe("0s");
    expect(formatElapsed(Number.NaN)).toBe("0s");
  });
});
