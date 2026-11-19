import { describe, expect, it } from "vitest";
import {
  HIGH_IMPACT, SECTIONS, canEditHigh, highKeys, modelAvailability, pending, sectionAnchor, sectionOfHash, shown, sourceOf, stage,
  type HighKey,
} from "@/lib/settingsPage";

const saved = (o: Partial<Record<HighKey, boolean>> = {}): Record<HighKey, boolean> => ({
  auto_fix_enabled: false, executor_enabled: false, executor_auto_approve_l0_l1: true, executor_hitl_enabled: false,
  change_auto_approve_standard: false, rbac_enforce: false, ...o,
});

describe("the General tab's three sections (MVP-2.9.0 N25 — the 2.8.0 spec's S8)", () => {
  it("each has an anchor, and an address's hash names one", () => {
    expect(SECTIONS).toEqual(["basics", "automation", "models"]);
    expect(SECTIONS.map(sectionAnchor)).toEqual(["settings-basics", "settings-automation", "settings-models"]);
    expect(sectionOfHash("#settings-models")).toBe("models");
    expect(sectionOfHash("#settings-automation")).toBe("automation");
    expect(sectionOfHash("")).toBeNull();
    expect(sectionOfHash("#settings-nope")).toBeNull();
    expect(sectionOfHash("#models")).toBeNull();
  });
});

describe("the high-impact switches are staged, never saved by a click", () => {
  it("six of them; the change switch only while change management is on", () => {
    expect(HIGH_IMPACT).toHaveLength(6);
    expect(highKeys({ change_management_enabled: true })).toEqual([...HIGH_IMPACT]);
    expect(highKeys({ change_management_enabled: false })).not.toContain("change_auto_approve_standard");
    expect(highKeys({})).toHaveLength(5);
  });
  it("a click stages a value; the switch shows what is staged", () => {
    const staged = stage(saved(), {}, "executor_enabled", true);
    expect(staged).toEqual({ executor_enabled: true });
    expect(shown(saved(), staged, "executor_enabled")).toBe(true);
    expect(shown(saved(), staged, "auto_fix_enabled")).toBe(false);
    expect(shown(saved(), { executor_auto_approve_l0_l1: false }, "executor_auto_approve_l0_l1")).toBe(false);   // a staged «off» over a saved «on»
  });
  it("clicking back to the saved value un-stages it", () => {
    const staged = stage(saved(), { executor_enabled: true, rbac_enforce: true }, "executor_enabled", false);
    expect(staged).toEqual({ rbac_enforce: true });
  });
  it("what is waiting to be saved: from → to, in the page's order, only real changes", () => {
    const staged = { rbac_enforce: true, executor_enabled: true, executor_auto_approve_l0_l1: true };
    expect(pending(saved(), staged, [...HIGH_IMPACT])).toEqual([
      { key: "executor_enabled", from: false, to: true },
      { key: "rbac_enforce", from: false, to: true },
    ]);
    expect(pending(saved(), {}, [...HIGH_IMPACT])).toEqual([]);
  });
  it("a switch that is not on the page is not saved", () => {
    expect(pending(saved(), { change_auto_approve_standard: true }, highKeys({ change_management_enabled: false }))).toEqual([]);
  });
});

describe("where a switch's value comes from", () => {
  it("the four stored ones: an administrator's stored value, else the settings file's default", () => {
    expect(sourceOf("executor_enabled", { overridden: ["executor_enabled"] })).toBe("stored");
    expect(sourceOf("auto_fix_enabled", { overridden: ["executor_enabled"] })).toBe("default");
    expect(sourceOf("executor_hitl_enabled", undefined)).toBe("default");
  });
  it("the two security toggles live in the settings file", () => {
    expect(sourceOf("rbac_enforce", { overridden: ["rbac_enforce"] })).toBe("file");
    expect(sourceOf("change_auto_approve_standard", undefined)).toBe("file");
  });
});

describe("who may change them", () => {
  it("with sign-in on: an administrator; with it off: anyone; unknown: nobody", () => {
    expect(canEditHigh({ auth_enabled: true, user: { is_admin: true } })).toBe(true);
    expect(canEditHigh({ auth_enabled: true, user: { is_admin: false } })).toBe(false);
    expect(canEditHigh({ auth_enabled: false, user: { is_admin: false } })).toBe(true);
    expect(canEditHigh(undefined)).toBe(false);
    expect(canEditHigh({ user: { is_admin: false } })).toBe(false);        // sign-in is not known to be off
  });
});

describe("a model's availability is read from the list — no model is called", () => {
  const presets = [{ value: "global.anthropic.claude-opus-5-5" }, { value: "global.anthropic.claude-sonnet-5-5" }];
  it("listed, not listed, or not known while there is no list", () => {
    expect(modelAvailability("global.anthropic.claude-opus-5-5", presets)).toBe("listed");
    expect(modelAvailability("global.anthropic.claude-opus-4-6-v1", presets)).toBe("unlisted");
    expect(modelAvailability("global.anthropic.claude-opus-5-5", undefined)).toBe("unknown");
    expect(modelAvailability("global.anthropic.claude-opus-5-5", [])).toBe("unknown");
    expect(modelAvailability("", presets)).toBe("unknown");
  });
});
