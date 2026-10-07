import { describe, it, expect } from "vitest";
import { adoptAccountParam, scopeKey, scopeMode, validScope } from "@/lib/accountScope";

const accounts = [{ id: 1 }, { id: 3 }];

describe("account scope (MVP-2.7.0 S4)", () => {
  it("is stored per user", () => {
    expect(scopeKey(7)).toBe("aiops-account-scope:7");
    expect(scopeKey(null)).toBe("aiops-account-scope:anon");
  });

  it("a stored account that no longer exists, or junk, falls back to All", () => {
    expect(validScope("3", accounts)).toBe(3);
    expect(validScope(3, accounts)).toBe(3);
    expect(validScope("9", accounts)).toBeNull();
    expect(validScope("x", accounts)).toBeNull();
    expect(validScope(null, accounts)).toBeNull();
    expect(validScope("-1", accounts)).toBeNull();
  });

  it("while the accounts are loading, a well-formed stored id is kept (not reset to All)", () => {
    expect(validScope("3", undefined)).toBe(3);
    expect(validScope("x", undefined)).toBeNull();
  });

  it.each([
    ["/app/issues", true, "active"], ["/app/issues", false, "active"],
    ["/app/issues/12", true, "active"], ["/app/issues/12", false, "locked"],
    ["/app/plans", true, "active"], ["/app/resources", false, "active"], ["/app/changes", true, "active"],
    ["/app/plans/5", true, "locked"], ["/app/changes/3", true, "locked"], ["/app/resources/9", true, "locked"],
    ["/app/overview", true, "notApplied"], ["/app/security", true, "notApplied"], ["/app/galaxy", true, "notApplied"],
    ["/app/chat", true, "notApplied"], ["/app/settings", true, "notApplied"], ["/app/issues/", true, "active"],
  ] as const)("%s (wide=%s) → %s", (path, wide, mode) => {
    expect(scopeMode(path, wide)).toBe(mode);
  });

  it("an old link's account parameter is adopted once and taken off the URL", () => {
    expect(adoptAccountParam("?tab=fix&account=3")).toEqual({ accountId: 3, search: "?tab=fix" });
    expect(adoptAccountParam("?account_id=4&status=planned")).toEqual({ accountId: 4, search: "?status=planned" });
    expect(adoptAccountParam("?account=3")).toEqual({ accountId: 3, search: "" });
    expect(adoptAccountParam("?tab=fix")).toBeNull();
    expect(adoptAccountParam("")).toBeNull();
  });

  it("a junk account parameter is still taken off the URL, and sets nothing", () => {
    expect(adoptAccountParam("?account=x&tab=fix")).toEqual({ accountId: null, search: "?tab=fix" });
  });
});
