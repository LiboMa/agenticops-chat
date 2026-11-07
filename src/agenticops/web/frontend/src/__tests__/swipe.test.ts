import { describe, it, expect } from "vitest";
import { swipeStep } from "@/lib/swipe";

describe("swipeStep", () => {
  it("a horizontal swipe left is next, right is previous; short or vertical is nothing", () => {
    expect(swipeStep(-80, 10)).toBe(1);
    expect(swipeStep(80, 5)).toBe(-1);
    expect(swipeStep(-30, 0)).toBe(0);
    expect(swipeStep(-80, 120)).toBe(0);
    expect(swipeStep(-40, 0, 30)).toBe(1);
  });
});
