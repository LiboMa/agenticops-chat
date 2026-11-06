import { describe, expect, it } from "vitest";
import { isReadOnly, navItemVisible, viewerActions } from "@/lib/permissions";

describe("isReadOnly", () => {
  it("is a signed-in viewer only", () => {
    expect(isReadOnly({ auth_enabled: true, user: { read_only: true } })).toBe(true);
    expect(isReadOnly({ auth_enabled: true, user: { read_only: false } })).toBe(false);
    expect(isReadOnly({ auth_enabled: true, user: null })).toBe(false);
    expect(isReadOnly({ auth_enabled: false, user: { read_only: true } })).toBe(false);
    expect(isReadOnly(undefined)).toBe(false);
  });
});

describe("navItemVisible", () => {
  it("hides Settings from a viewer and nothing else", () => {
    expect(navItemVisible("settings", true)).toBe(false);
    expect(navItemVisible("settings", false)).toBe(true);
    for (const id of ["chat", "issues", "reports", "plans", "resources", "schedules", "galaxy", "security"]) {
      expect(navItemVisible(id, true)).toBe(true);
    }
  });
});

describe("viewerActions", () => {
  it("keeps only Ask Agent", () => {
    const menu = ["runRca", "markResolved", "dismiss", "askAgent", "reject", "copyAsNew"].map((key) => ({ key }));
    expect(viewerActions(menu)).toEqual([{ key: "askAgent" }]);
    expect(viewerActions([])).toEqual([]);
  });
});
