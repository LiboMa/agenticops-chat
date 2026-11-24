import { describe, expect, it } from "vitest";
import { changesState } from "@/lib/changesEnabled";

describe("whether change management is on — said only when it is known (MVP-2.9.0 N22)", () => {
  it("is loading before the settings arrived: never «disabled» for a moment", () => {
    expect(changesState({ data: undefined, isError: false })).toBe("loading");
  });
  it("is failed when the settings could not be read: not «disabled» either", () => {
    expect(changesState({ data: undefined, isError: true })).toBe("failed");
  });
  it("is on or off once the settings say so — also when a later refresh failed", () => {
    expect(changesState({ data: { change_management_enabled: true }, isError: false })).toBe("on");
    expect(changesState({ data: { change_management_enabled: false }, isError: false })).toBe("off");
    expect(changesState({ data: {}, isError: false })).toBe("off");
    expect(changesState({ data: { change_management_enabled: true }, isError: true })).toBe("on");
  });
});
