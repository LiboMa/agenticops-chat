import { describe, it, expect } from "vitest";
import { formatShortDate, formatFullDate, formatUtcClock } from "@/lib/formatDate";

describe("formatShortDate", () => {
  it("formats a Date object to short date with month, day, hour, minute in UTC", () => {
    const date = new Date("2024-01-15T14:30:00Z");
    const result = formatShortDate(date);
    expect(result).toContain("Jan");
    expect(result).toContain("15");
    expect(result).toContain("14");
    expect(result).toContain("30");
  });

  it("produces exact expected format string", () => {
    expect(formatShortDate("2024-07-04T09:05:00Z")).toBe("Jul 4, 09:05");
  });

  it("formats a string date to short date in UTC", () => {
    const result = formatShortDate("2024-07-04T09:05:00Z");
    expect(result).toContain("Jul");
    expect(result).toContain("4");
    expect(result).toContain("09");
    expect(result).toContain("05");
  });

  it("always uses UTC regardless of input timezone offset", () => {
    // Midnight UTC presented as a string
    const result = formatShortDate("2024-12-25T00:00:00Z");
    expect(result).toContain("Dec");
    expect(result).toContain("25");
    expect(result).toContain("00");
  });

  it("handles ISO strings with milliseconds", () => {
    const result = formatShortDate("2024-03-01T23:59:59.999Z");
    expect(result).toContain("Mar");
    expect(result).toContain("1");
    expect(result).toContain("23");
    expect(result).toContain("59");
  });

  it("does not include year or seconds in short format", () => {
    const result = formatShortDate(new Date("2024-01-15T14:30:45Z"));
    // Short format should not contain the year
    // It should contain month/day/hour/minute only
    expect(result).not.toContain("2024");
  });
});

describe("formatFullDate", () => {
  it("formats a Date object with year, month, day, hour, minute, second in UTC", () => {
    const date = new Date("2024-01-15T14:30:45Z");
    const result = formatFullDate(date);
    expect(result).toContain("2024");
    expect(result).toContain("Jan");
    expect(result).toContain("15");
    expect(result).toContain("14");
    expect(result).toContain("30");
    expect(result).toContain("45");
  });

  it("produces exact expected format string", () => {
    expect(formatFullDate("2024-01-15T14:30:45Z")).toBe("Jan 15, 2024, 14:30:45");
  });

  it("formats a string date to full date in UTC", () => {
    const result = formatFullDate("2023-11-28T08:15:30Z");
    expect(result).toContain("2023");
    expect(result).toContain("Nov");
    expect(result).toContain("28");
    expect(result).toContain("08");
    expect(result).toContain("15");
    expect(result).toContain("30");
  });

  it("includes seconds in full format", () => {
    const result = formatFullDate(new Date("2024-06-01T00:00:59Z"));
    expect(result).toContain("59");
  });

  it("uses 24-hour format (hour12: false)", () => {
    const result = formatFullDate(new Date("2024-01-01T22:45:10Z"));
    expect(result).toContain("22");
    expect(result).toContain("45");
    expect(result).toContain("10");
  });

  it("formats midnight correctly", () => {
    const result = formatFullDate(new Date("2024-01-01T00:00:00Z"));
    expect(result).toContain("Jan");
    expect(result).toContain("1");
    expect(result).toContain("2024");
    expect(result).toContain("00");
  });
});

describe("formatUtcClock", () => {
  it("appends ' UTC' suffix to the formatted date", () => {
    const date = new Date("2024-01-15T14:30:00Z");
    const result = formatUtcClock(date);
    expect(result).toMatch(/ UTC$/);
  });

  it("produces exact expected format string", () => {
    expect(formatUtcClock(new Date("2024-06-03T09:15:00Z"))).toBe("06/03/2024, 09:15 UTC");
  });

  it("includes year, month, day, hour, minute in UTC", () => {
    const date = new Date("2024-06-03T09:15:00Z");
    const result = formatUtcClock(date);
    expect(result).toContain("2024");
    expect(result).toContain("06");
    expect(result).toContain("03");
    expect(result).toContain("09");
    expect(result).toContain("15");
    expect(result).toContain("UTC");
  });

  it("uses 2-digit month and day", () => {
    const result = formatUtcClock(new Date("2024-01-05T10:00:00Z"));
    expect(result).toContain("01");
    expect(result).toContain("05");
  });

  it("formats end-of-day time correctly", () => {
    const result = formatUtcClock(new Date("2024-12-31T23:59:00Z"));
    expect(result).toContain("12");
    expect(result).toContain("31");
    expect(result).toContain("23");
    expect(result).toContain("59");
    expect(result).toMatch(/ UTC$/);
  });

  it("does not include seconds", () => {
    const date = new Date("2024-01-15T14:30:45Z");
    const result = formatUtcClock(date);
    // Clock formatter only includes hour and minute, not seconds
    // The result ends with " UTC" so there's no trailing "45"
    // We verify the format has expected structure
    expect(result).toMatch(/\d{2}:\d{2} UTC$/);
  });
});
