import { describe, it, expect } from "vitest";
import { adoptAccountParam, scopeKey, scopeMode, validScope, scopeSelect } from "@/lib/accountScope";

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
    ["/app/overview", true, "notApplied"], ["/app/security", true, "active"], ["/app/galaxy", true, "notApplied"],
    ["/app/chat", true, "active"], ["/app/chat/abc", true, "locked"], ["/app/settings", true, "notApplied"], ["/app/issues/", true, "active"],
    ["/app/inbox", true, "active"], ["/app/inbox", false, "active"],   // MVP-2.8.0 S2: the workbench follows the scope
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

describe("review m4 / m5", () => {
  it("when the account list failed to load, the scope is All — a stale id must not empty every list", () => {
    expect(validScope("3", undefined, true)).toBeNull();
    expect(validScope("3", accounts, true)).toBeNull();
  });
  it("an adopted id is checked like a stored one: an unknown account from an old link sets nothing", () => {
    expect(validScope(adoptAccountParam("?account=999")!.accountId, accounts)).toBeNull();
    expect(validScope(adoptAccountParam("?account=3")!.accountId, accounts)).toBe(3);
  });
});

describe("scopeSelect — the new frame's account select", () => {
  const free = { value: 3, disabled: false, why: null };
  it("on a lens the choice is the person's, whatever the classic rule says of the address", () => {
    expect(scopeSelect({ lens: true, mode: "notApplied", locked: undefined, accountId: 3 })).toEqual(free);
    expect(scopeSelect({ lens: true, mode: "locked", locked: undefined, accountId: null })).toEqual({ value: null, disabled: false, why: null });
  });
  it("on a hosted list it filters, as the classic top bar's did", () => {
    expect(scopeSelect({ lens: false, mode: "active", locked: undefined, accountId: 3 })).toEqual(free);
  });
  it("a hosted detail page, and a page the scope does not filter, show it disabled and say why", () => {
    expect(scopeSelect({ lens: false, mode: "locked", locked: undefined, accountId: 3 })).toEqual({ value: 3, disabled: true, why: "locked" });
    expect(scopeSelect({ lens: false, mode: "notApplied", locked: undefined, accountId: 3 })).toEqual({ value: 3, disabled: true, why: "notApplied" });
  });
  it("an open chat shows its own account, not the person's choice", () => {
    expect(scopeSelect({ lens: false, mode: "locked", locked: 5, accountId: 3 })).toEqual({ value: 5, disabled: true, why: "lockedChat" });
    expect(scopeSelect({ lens: false, mode: "locked", locked: null, accountId: 3 })).toEqual({ value: null, disabled: true, why: "lockedChat" });
  });
});
