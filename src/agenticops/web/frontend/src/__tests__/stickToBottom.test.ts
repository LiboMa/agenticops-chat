import { describe, it, expect } from "vitest";
import { nextStick } from "@/lib/stickToBottom";

describe("nextStick — only the user scrolls a chat away from its newest message", () => {
  it("reaching the bottom always sticks", () => {
    expect(nextStick(false, 20, false)).toBe(true);
    expect(nextStick(false, 20, true)).toBe(true);
  });
  it("a scroll the user made away from the bottom unsticks", () => expect(nextStick(true, 900, true)).toBe(false));
  it("a scroll nobody made (rows measured taller, the list adjusted) keeps it stuck", () =>
    expect(nextStick(true, 2104, false)).toBe(true));
  it("not stuck stays not stuck until the bottom is reached", () => expect(nextStick(false, 900, false)).toBe(false));
});
