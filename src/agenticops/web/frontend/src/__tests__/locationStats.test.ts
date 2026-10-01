import { describe, it, expect } from "vitest";
import { ratePct } from "@/lib/locationStats";

describe("ratePct", () => {
  it("rounds a rate to a whole percent; no denominator is a dash, not 0%", () => {
    expect(ratePct(0.8333)).toBe("83%");
    expect(ratePct(1)).toBe("100%");
    expect(ratePct(0)).toBe("0%");
    expect(ratePct(null)).toBe("—");
  });
});
