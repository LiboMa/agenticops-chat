import { describe, expect, it } from "vitest";
import { lensOf, shellTitle } from "@/newui/lib/shell";

describe("lensOf — the lens tab an address belongs to", () => {
  it("a lens is itself", () => {
    expect(lensOf("/app/new/decide", undefined)).toBe("decide");
    expect(lensOf("/app/new/decide/I12", undefined)).toBe("decide");
    expect(lensOf("/app/new/live/I12%3Arun", undefined)).toBe("live");
    expect(lensOf("/app/new/world", undefined)).toBe("world");
  });
  it("a story is a page of the lens it was opened from, «待决» unless said", () => {
    expect(lensOf("/app/new/story/I12", "live")).toBe("live");
    expect(lensOf("/app/new/story/I12", "world")).toBe("world");
    expect(lensOf("/app/new/story/I12", undefined)).toBe("decide");
    expect(lensOf("/app/new/story/I12", "elsewhere")).toBe("decide");
  });
  it("no lens is selected on a hosted page, nor on a NewUI page that is not a lens", () => {
    // until round 3 every other address answered «待决»: its tab showed selected over a classic page
    for (const p of ["/app/reports", "/app/issues/12", "/app/chat/abc", "/app", "/app/settings", "/app/new/items", "/app/new/nope", "/app/newer"]) {
      expect(lensOf(p, undefined)).toBeNull();
      expect(lensOf(p, "live")).toBeNull();
    }
  });
});

describe("shellTitle — the browser tab says which page it is", () => {
  it("a lens by itself, a story by its item", () => {
    expect(shellTitle("/app/new/decide/I12", { lens: "待决", story: "经过", section: null })).toBe("AgenticOps · 待决");
    expect(shellTitle("/app/new/story/C3", { lens: "现场", story: "经过", section: null })).toBe("AgenticOps · C#3 经过");
  });
  it("a hosted page is titled by its section, as the classic top bar titled it", () => {
    expect(shellTitle("/app/reports/7", { lens: null, story: "经过", section: "报告" })).toBe("AgenticOps · 报告");
    expect(shellTitle("/app/settings", { lens: null, story: "经过", section: "Settings" })).toBe("AgenticOps · Settings");
  });
  it("a page with neither says only the product", () => {
    expect(shellTitle("/app", { lens: null, story: "经过", section: null })).toBe("AgenticOps");
    expect(shellTitle("/app/new/items", { lens: null, story: "经过", section: "" })).toBe("AgenticOps");
  });
});
