import { describe, it, expect } from "vitest";
import { nextMenuIndex } from "@/lib/menuNav";

describe("nextMenuIndex (final review Minor 8: the ⋯ menu by keyboard)", () => {
  const all = [false, false, false]; // disabled flags
  it("ArrowDown / ArrowUp move one item and wrap", () => {
    expect(nextMenuIndex(0, "ArrowDown", all)).toBe(1);
    expect(nextMenuIndex(2, "ArrowDown", all)).toBe(0);
    expect(nextMenuIndex(0, "ArrowUp", all)).toBe(2);
  });
  it("Home / End go to the first / last item; from nowhere (-1) ArrowDown is the first, ArrowUp the last", () => {
    expect(nextMenuIndex(1, "Home", all)).toBe(0);
    expect(nextMenuIndex(1, "End", all)).toBe(2);
    expect(nextMenuIndex(-1, "ArrowDown", all)).toBe(0);
    expect(nextMenuIndex(-1, "ArrowUp", all)).toBe(2);
  });
  it("disabled items are skipped; with none enabled there is nowhere to go (-1)", () => {
    expect(nextMenuIndex(0, "ArrowDown", [false, true, false])).toBe(2);
    expect(nextMenuIndex(2, "ArrowUp", [false, true, false])).toBe(0);
    expect(nextMenuIndex(-1, "Home", [true, false, false])).toBe(1);
    expect(nextMenuIndex(-1, "End", [false, false, true])).toBe(1);
    expect(nextMenuIndex(0, "ArrowDown", [true, true])).toBe(-1);
    expect(nextMenuIndex(-1, "ArrowDown", [])).toBe(-1);
  });
});
