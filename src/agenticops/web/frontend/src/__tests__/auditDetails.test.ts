import { describe, it, expect } from "vitest";
import { auditFilters, changeSummary, isEmptyDetails } from "@/components/settings/AuditTab";

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

// MVP-2.9.0 N25 — a settings change carries no `details`, only the value before and after.
describe("a row without details shows what it changed", () => {
  it("old → new, key by key", () => {
    expect(changeSummary({ executor_enabled: false }, { executor_enabled: true })).toBe("executor_enabled: false → true");
    expect(changeSummary({ a: "x", b: 1 }, { a: "y", c: 2 })).toBe("a: x → y; b: 1 → —; c: — → 2");
    expect(changeSummary({ b: 1 }, { a: 2 })).toBe("a: — → 2; b: 1 → —");        // by name, not by where it came from
  });
  it("a row that records only one side still says it", () => {
    expect(changeSummary(null, { a: 1 })).toBe("a: — → 1");
    expect(changeSummary({ a: 1 }, null)).toBe("a: 1 → —");
  });
  it("null when the row records neither", () => {
    expect(changeSummary(null, null)).toBeNull();
    expect(changeSummary({}, undefined)).toBeNull();
  });
});

describe("the filters an address asks for (the Settings page's link to the records of settings changes)", () => {
  it("a known entity type and 1–720 hours", () => {
    expect(auditFilters(new URLSearchParams("entity=system&hours=720"))).toEqual({ entity: "system", hours: 720 });
  });
  it("anything else is the default", () => {
    expect(auditFilters(new URLSearchParams(""))).toEqual({ entity: "", hours: 24 });
    expect(auditFilters(new URLSearchParams("entity=nope&hours=721"))).toEqual({ entity: "", hours: 24 });
    expect(auditFilters(new URLSearchParams("hours=0"))).toEqual({ entity: "", hours: 24 });
    expect(auditFilters(new URLSearchParams("hours=1.5"))).toEqual({ entity: "", hours: 24 });
  });
});
