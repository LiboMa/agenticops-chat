import { describe, it, expect } from "vitest";
import {
  parseCronFields,
  buildCron,
  validateCron,
  describeCron,
  CRON_PRESETS,
  MINUTE_OPTIONS,
  HOUR_OPTIONS,
  DOM_OPTIONS,
  MONTH_OPTIONS,
  DOW_OPTIONS,
} from "@/lib/cronHelpers";
import type { CronFields } from "@/lib/cronHelpers";

describe("parseCronFields", () => {
  it("parses a standard 5-field cron expression", () => {
    const result = parseCronFields("0 9 * * 1");
    expect(result).toEqual({
      minute: "0",
      hour: "9",
      dom: "*",
      month: "*",
      dow: "1",
    });
  });

  it("parses expression with step values", () => {
    const result = parseCronFields("*/5 */6 */2 */3 *");
    expect(result).toEqual({
      minute: "*/5",
      hour: "*/6",
      dom: "*/2",
      month: "*/3",
      dow: "*",
    });
  });

  it("handles extra whitespace between fields", () => {
    const result = parseCronFields("  0   0   1   *   *  ");
    expect(result).toEqual({
      minute: "0",
      hour: "0",
      dom: "1",
      month: "*",
      dow: "*",
    });
  });

  it("returns null for fewer than 5 fields", () => {
    expect(parseCronFields("0 0 * *")).toBeNull();
  });

  it("returns null for more than 5 fields", () => {
    expect(parseCronFields("0 0 * * * *")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseCronFields("")).toBeNull();
  });

  it("returns null for whitespace-only string", () => {
    expect(parseCronFields("   ")).toBeNull();
  });

  it("parses comma-separated values", () => {
    const result = parseCronFields("0 0,12 * * 1,3,5");
    expect(result).toEqual({
      minute: "0",
      hour: "0,12",
      dom: "*",
      month: "*",
      dow: "1,3,5",
    });
  });

  it("parses range values", () => {
    const result = parseCronFields("0 9 * * 1-5");
    expect(result).toEqual({
      minute: "0",
      hour: "9",
      dom: "*",
      month: "*",
      dow: "1-5",
    });
  });
});

describe("buildCron", () => {
  it("constructs a space-separated cron string from CronFields", () => {
    const fields: CronFields = {
      minute: "30",
      hour: "9",
      dom: "1",
      month: "6",
      dow: "1-5",
    };
    expect(buildCron(fields)).toBe("30 9 1 6 1-5");
  });

  it("constructs all-wildcards expression", () => {
    const fields: CronFields = {
      minute: "*",
      hour: "*",
      dom: "*",
      month: "*",
      dow: "*",
    };
    expect(buildCron(fields)).toBe("* * * * *");
  });

  it("round-trips with parseCronFields", () => {
    const original = "0 */6 * * *";
    const parsed = parseCronFields(original);
    expect(parsed).not.toBeNull();
    expect(buildCron(parsed!)).toBe(original);
  });

  it("round-trips complex expressions", () => {
    const original = "*/15 0,12 1 */3 1-5";
    const parsed = parseCronFields(original);
    expect(parsed).not.toBeNull();
    expect(buildCron(parsed!)).toBe(original);
  });
});

describe("validateCron", () => {
  it("returns valid for a correct expression", () => {
    expect(validateCron("0 9 * * 1")).toEqual({ valid: true });
  });

  it("returns valid for all-wildcards", () => {
    expect(validateCron("* * * * *")).toEqual({ valid: true });
  });

  it("returns valid for step values", () => {
    expect(validateCron("*/5 */6 */2 */3 *")).toEqual({ valid: true });
  });

  it("returns valid for comma-separated values", () => {
    expect(validateCron("0 0,12 * * 1,3,5")).toEqual({ valid: true });
  });

  it("returns valid for range values", () => {
    expect(validateCron("0 9 * * 1-5")).toEqual({ valid: true });
  });

  it("returns error for wrong field count (too few)", () => {
    const result = validateCron("0 9 *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Expected 5 fields, got 3");
  });

  it("returns error for wrong field count (too many)", () => {
    const result = validateCron("0 9 * * * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Expected 5 fields, got 6");
  });

  it("returns error for invalid syntax in minute field", () => {
    const result = validateCron("abc 0 * * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Minute");
    expect(result.error).toContain("invalid syntax");
  });

  it("returns error for invalid syntax in hour field", () => {
    const result = validateCron("0 abc * * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Hour");
    expect(result.error).toContain("invalid syntax");
  });

  it("returns error for invalid syntax in dom field", () => {
    const result = validateCron("0 0 abc * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Day of month");
    expect(result.error).toContain("invalid syntax");
  });

  it("returns error for invalid syntax in month field", () => {
    const result = validateCron("0 0 * abc *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Month");
    expect(result.error).toContain("invalid syntax");
  });

  it("returns error for invalid syntax in dow field", () => {
    const result = validateCron("0 0 * * abc");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Day of week");
    expect(result.error).toContain("invalid syntax");
  });

  it("returns error when minute exceeds 59", () => {
    const result = validateCron("60 0 * * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Minute");
    expect(result.error).toContain("60");
    expect(result.error).toContain("exceeds max 59");
  });

  it("returns error when hour exceeds 23", () => {
    const result = validateCron("0 24 * * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Hour");
    expect(result.error).toContain("24");
    expect(result.error).toContain("exceeds max 23");
  });

  it("returns error when dom exceeds 31", () => {
    const result = validateCron("0 0 32 * *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Day of month");
    expect(result.error).toContain("32");
    expect(result.error).toContain("exceeds max 31");
  });

  it("returns error when month exceeds 12", () => {
    const result = validateCron("0 0 * 13 *");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Month");
    expect(result.error).toContain("13");
    expect(result.error).toContain("exceeds max 12");
  });

  it("returns error when dow exceeds 7", () => {
    const result = validateCron("0 0 * * 8");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("Day of week");
    expect(result.error).toContain("8");
    expect(result.error).toContain("exceeds max 7");
  });

  it("validates boundary values (max allowed)", () => {
    expect(validateCron("59 23 31 12 7")).toEqual({ valid: true });
  });

  it("validates zero values", () => {
    expect(validateCron("0 0 1 1 0")).toEqual({ valid: true });
  });
});

describe("describeCron", () => {
  it("returns 'Invalid expression' for non-5-field input", () => {
    expect(describeCron("bad")).toBe("Invalid expression");
  });

  it("returns 'Invalid expression' for empty string", () => {
    expect(describeCron("")).toBe("Invalid expression");
  });

  it("describes every minute (* * * * *)", () => {
    const result = describeCron("* * * * *");
    expect(result).toBe("Every minute");
  });

  it("describes step minutes (*/5 * * * *)", () => {
    const result = describeCron("*/5 * * * *");
    expect(result).toContain("Every 5 minutes");
  });

  it("describes hourly at :00 (0 * * * *)", () => {
    const result = describeCron("0 * * * *");
    expect(result.toLowerCase()).toContain("every hour");
  });

  it("describes specific time (0 9 * * *)", () => {
    const result = describeCron("0 9 * * *");
    expect(result).toContain("09:00");
  });

  it("describes midnight (0 0 * * *)", () => {
    const result = describeCron("0 0 * * *");
    expect(result).toContain("00:00");
  });

  it("describes step hours (0 */6 * * *)", () => {
    const result = describeCron("0 */6 * * *");
    expect(result).toContain("every 6 hours");
  });

  it("describes multiple hours (0 0,12 * * *)", () => {
    const result = describeCron("0 0,12 * * *");
    expect(result.toLowerCase()).toContain("hours");
  });

  it("describes weekdays (0 9 * * 1-5)", () => {
    const result = describeCron("0 9 * * 1-5");
    expect(result.toLowerCase()).toContain("weekdays");
  });

  it("describes weekends (0 9 * * 0,6)", () => {
    const result = describeCron("0 9 * * 0,6");
    expect(result.toLowerCase()).toContain("weekends");
  });

  it("describes specific day of week by name (0 0 * * 1)", () => {
    const result = describeCron("0 0 * * 1");
    expect(result).toContain("Monday");
  });

  it("describes Sunday (0 0 * * 0)", () => {
    const result = describeCron("0 0 * * 0");
    expect(result).toContain("Sunday");
  });

  it("describes specific day of month (0 0 15 * *)", () => {
    const result = describeCron("0 0 15 * *");
    expect(result).toContain("day 15");
  });

  it("describes step dom (0 0 */2 * *)", () => {
    const result = describeCron("0 0 */2 * *");
    expect(result).toContain("every 2 days");
  });

  it("describes specific month (0 0 1 6 *)", () => {
    const result = describeCron("0 0 1 6 *");
    expect(result).toContain("Jun");
  });

  it("describes step months (0 0 1 */3 *)", () => {
    const result = describeCron("0 0 1 */3 *");
    expect(result).toContain("every 3 months");
  });

  it("first character is uppercase", () => {
    const result = describeCron("0 9 * * *");
    expect(result[0]).toBe(result[0].toUpperCase());
  });

  it("describes all CRON_PRESETS without returning 'Invalid expression'", () => {
    for (const preset of CRON_PRESETS) {
      const desc = describeCron(preset.cron);
      expect(desc).not.toBe("Invalid expression");
    }
  });
});

describe("CRON_PRESETS", () => {
  it("contains 7 presets", () => {
    expect(CRON_PRESETS).toHaveLength(7);
  });

  it("each preset has required fields", () => {
    for (const preset of CRON_PRESETS) {
      expect(preset).toHaveProperty("label");
      expect(preset).toHaveProperty("cron");
      expect(preset).toHaveProperty("desc");
      expect(preset).toHaveProperty("icon");
      expect(typeof preset.label).toBe("string");
      expect(typeof preset.cron).toBe("string");
      expect(typeof preset.desc).toBe("string");
      expect(typeof preset.icon).toBe("string");
    }
  });

  it("all preset cron expressions pass validation", () => {
    for (const preset of CRON_PRESETS) {
      const result = validateCron(preset.cron);
      expect(result.valid).toBe(true);
    }
  });

  it("all preset icons are valid icon types", () => {
    const validIcons = ["clock", "clock-6", "moon", "sun", "sunrise", "calendar", "calendar-days"];
    for (const preset of CRON_PRESETS) {
      expect(validIcons).toContain(preset.icon);
    }
  });

  it("all preset labels are non-empty", () => {
    for (const preset of CRON_PRESETS) {
      expect(preset.label.length).toBeGreaterThan(0);
    }
  });
});

describe("option constants", () => {
  it("MINUTE_OPTIONS is a non-empty array of strings", () => {
    expect(Array.isArray(MINUTE_OPTIONS)).toBe(true);
    expect(MINUTE_OPTIONS.length).toBeGreaterThan(0);
    for (const opt of MINUTE_OPTIONS) {
      expect(typeof opt).toBe("string");
    }
  });

  it("HOUR_OPTIONS is a non-empty array of strings", () => {
    expect(Array.isArray(HOUR_OPTIONS)).toBe(true);
    expect(HOUR_OPTIONS.length).toBeGreaterThan(0);
    for (const opt of HOUR_OPTIONS) {
      expect(typeof opt).toBe("string");
    }
  });

  it("DOM_OPTIONS is a non-empty array of strings", () => {
    expect(Array.isArray(DOM_OPTIONS)).toBe(true);
    expect(DOM_OPTIONS.length).toBeGreaterThan(0);
    for (const opt of DOM_OPTIONS) {
      expect(typeof opt).toBe("string");
    }
  });

  it("MONTH_OPTIONS is a non-empty array of strings", () => {
    expect(Array.isArray(MONTH_OPTIONS)).toBe(true);
    expect(MONTH_OPTIONS.length).toBeGreaterThan(0);
    for (const opt of MONTH_OPTIONS) {
      expect(typeof opt).toBe("string");
    }
  });

  it("DOW_OPTIONS is a non-empty array with value and label", () => {
    expect(Array.isArray(DOW_OPTIONS)).toBe(true);
    expect(DOW_OPTIONS.length).toBeGreaterThan(0);
    for (const opt of DOW_OPTIONS) {
      expect(opt).toHaveProperty("value");
      expect(opt).toHaveProperty("label");
      expect(typeof opt.value).toBe("string");
      expect(typeof opt.label).toBe("string");
    }
  });
});
