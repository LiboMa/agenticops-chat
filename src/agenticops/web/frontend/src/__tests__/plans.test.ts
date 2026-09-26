import { describe, it, expect } from "vitest";
import { isTerminalChange, toQuery } from "@/lib/plans";

describe("toQuery", () => {
  it("drops undefined, null and empty-string values", () => {
    expect(toQuery({ status: "draft", account_id: undefined, requested_by: null, period: "" })).toBe("?status=draft");
  });
  it("keeps 0: a zero offset is a value, not an absent one", () => {
    expect(toQuery({ offset: 0, limit: 50 })).toBe("?offset=0&limit=50");
  });
  it('returns "" when there is nothing to send', () => {
    expect(toQuery({})).toBe("");
  });
});

describe("isTerminalChange", () => {
  it("is true for a terminal status, false for a moving one and for undefined", () => {
    expect(isTerminalChange("rolled_back")).toBe(true);
    expect(isTerminalChange("under_review")).toBe(false);
    expect(isTerminalChange(undefined)).toBe(false);
  });
});
