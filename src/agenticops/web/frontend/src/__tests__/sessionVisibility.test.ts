import { describe, it, expect } from "vitest";
import { canChangeVisibility, canManage, otherVisibility, visibilityTag } from "@/lib/sessionVisibility";

describe("session visibility", () => {
  it("tags workspace sessions and other people's private ones, never the reader's own", () => {
    expect(visibilityTag({ visibility: "workspace", owned_by_me: false }, true)).toBe("workspace");
    expect(visibilityTag({ visibility: "workspace", owned_by_me: true }, true)).toBe("workspace");
    expect(visibilityTag({ visibility: "private", owned_by_me: true }, true)).toBeNull();
    expect(visibilityTag({ visibility: "private", owned_by_me: false }, true)).toBe("othersPrivate");
  });

  it("tags nothing with auth off, and reads a missing field as workspace", () => {
    expect(visibilityTag({ visibility: "private", owned_by_me: false }, false)).toBeNull();
    expect(visibilityTag({}, true)).toBe("workspace");
  });

  it("lets only the logged-in owner flip it, to the other value", () => {
    expect(canChangeVisibility({ owned_by_me: true }, true)).toBe(true);
    expect(canChangeVisibility({ owned_by_me: false }, true)).toBe(false);
    expect(canChangeVisibility({ owned_by_me: true }, false)).toBe(false);
    expect(otherVisibility({ visibility: "private" })).toBe("workspace");
    expect(otherVisibility({ visibility: "workspace" })).toBe("private");
    expect(otherVisibility({})).toBe("private");
  });

  it("lets anyone manage unless the server says the session is someone else's", () => {
    expect(canManage({ can_manage: true })).toBe(true);
    expect(canManage({})).toBe(true);
    expect(canManage({ can_manage: false })).toBe(false);
  });
});
