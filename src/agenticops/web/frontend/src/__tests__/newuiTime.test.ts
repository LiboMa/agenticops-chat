import { describe, expect, it } from "vitest";
import { utcHm, utcStamp } from "@/newui/lib/time";

const NOW = Date.parse("2026-11-17T12:00:00Z");

describe("NewUI times are UTC", () => {
  it("utcHm gives the UTC hour and minute, whatever the browser's zone", () => {
    expect(utcHm(Date.parse("2026-11-17T09:32:41Z"))).toBe("09:32");
    expect(utcHm("2026-11-17T09:32:41+08:00")).toBe("01:32");
    expect(utcHm("2026-11-17T09:32:41")).toBe("09:32");          // a naive API time is UTC
    expect(utcHm(new Date(NOW))).toBe("12:00");
  });

  it("utcStamp adds the day, and the year only when it is another one", () => {
    expect(utcStamp("2026-11-16T09:32:00Z", NOW)).toBe("11-16 09:32");
    expect(utcStamp("2025-12-31T23:59:00Z", NOW)).toBe("2025-12-31 23:59");
  });

  it("shows a dash for no time or a broken one", () => {
    for (const bad of [null, undefined, "not a date"]) {
      expect(utcHm(bad)).toBe("—");
      expect(utcStamp(bad, NOW)).toBe("—");
    }
  });
});
