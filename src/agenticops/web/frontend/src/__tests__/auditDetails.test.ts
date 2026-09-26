import { describe, it, expect } from "vitest";
import { isEmptyDetails } from "@/components/settings/AuditTab";

// M7 — an empty details object (the ORM default) renders as "-", like null/undefined.
describe("isEmptyDetails (M7)", () => {
  it("treats null, undefined and an empty object as empty", () => {
    expect(isEmptyDetails(null)).toBe(true);
    expect(isEmptyDetails(undefined)).toBe(true);
    expect(isEmptyDetails({})).toBe(true);
  });
  it("treats an object with own keys as non-empty", () => {
    expect(isEmptyDetails({ a: 1 })).toBe(false);
  });
});
