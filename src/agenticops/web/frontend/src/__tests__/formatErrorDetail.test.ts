import { describe, it, expect } from "vitest";
import { formatErrorDetail } from "@/api/client";

describe("formatErrorDetail", () => {
  it("returns a string detail as-is", () => {
    expect(formatErrorDetail("Fix plan 7 is not pending approval")).toBe("Fix plan 7 is not pending approval");
  });
  it('joins a FastAPI 422 list as "field: msg; field: msg", dropping the body/query prefix', () => {
    const detail = [
      { type: "string_too_long", loc: ["body", "reason"], msg: "String should have at most 2000 characters", input: "x" },
      { type: "less_than_equal", loc: ["query", "limit"], msg: "Input should be less than or equal to 500", input: "9999" },
    ];
    expect(formatErrorDetail(detail)).toBe(
      "reason: String should have at most 2000 characters; limit: Input should be less than or equal to 500",
    );
  });
  it('joins a nested loc with "." after the prefix', () => {
    expect(formatErrorDetail([{ loc: ["body", "targets", 0], msg: "Input should be a valid string" }])).toBe(
      "targets.0: Input should be a valid string",
    );
  });
  it("uses the bare msg for an item without loc", () => {
    expect(formatErrorDetail([{ msg: "Field required" }])).toBe("Field required");
  });
  it("renders any other value as JSON", () => {
    expect(formatErrorDetail({ code: "conflict", status: "approved" })).toBe('{"code":"conflict","status":"approved"}');
  });
  it('returns "" for undefined', () => {
    expect(formatErrorDetail(undefined)).toBe("");
  });
});
