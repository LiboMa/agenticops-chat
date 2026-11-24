import { describe, it, expect } from "vitest";
import { thinkingTail } from "@/lib/thinking";

describe("thinkingTail — one line of the model's latest thinking", () => {
  it("the last sentence, on one line", () => {
    expect(thinkingTail("Weighing the services. C reads the full pool.\nSo C is first.")).toBe("So C is first.");
    expect(thinkingTail("先看连接池。\n再看重试")).toBe("再看重试");
  });
  it("a sentence still being written is the tail", () => {
    expect(thinkingTail("Checked A. Now looking at")).toBe("Now looking at");
  });
  it("long tails are cut from the left", () => {
    const t = thinkingTail("x".repeat(300), 160);
    expect(t.length).toBe(160);
    expect(t.startsWith("…")).toBe(true);
  });
  it("empty stays empty", () => expect(thinkingTail("  ")).toBe(""));
});
