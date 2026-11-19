import { describe, expect, it } from "vitest";
import {
  HIGH_IMPACT, SECTIONS, canEditHigh, highKeys, modelAvailability, heldVar, pending, sectionAnchor, sectionOfHash, shown, shownTab, sourceOf, stage,
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

describe("shownTab (MVP-2.9.0 N27)", () => {
  it("the audit log is offered only to who may read it: anyone else who follows a link to it gets the first tab", () => {
    expect(shownTab("audit", false)).toBe("general");
    expect(shownTab("audit", true)).toBe("audit");
  });
  it("every other tab is the one asked for", () => {
    for (const tab of ["general", "accounts", "messaging", "kb", "skills", "mcp", "memory"] as const) {
      expect(shownTab(tab, false)).toBe(tab);
      expect(shownTab(tab, true)).toBe(tab);
    }
  });
});

describe("a switch the environment holds (MVP-2.9.0 N27, review)", () => {
  const info = { overridden: ["executor_enabled", "auto_fix_enabled"], locked: { executor_enabled: false, executor_hitl_enabled: true } };

  it("its source is the environment, whatever is stored", () => {
    expect(sourceOf("executor_enabled", info)).toBe("environment");
    expect(sourceOf("executor_hitl_enabled", info)).toBe("environment");
    expect(sourceOf("auto_fix_enabled", info)).toBe("stored");
    expect(sourceOf("executor_auto_approve_l0_l1", info)).toBe("default");
    expect(sourceOf("rbac_enforce", info)).toBe("file");
  });
  it("names the variable and the value it holds", () => {
    expect(heldVar("executor_enabled", info)).toBe("AIOPS_EXECUTOR_ENABLED=false");
    expect(heldVar("executor_hitl_enabled", info)).toBe("AIOPS_EXECUTOR_HITL_ENABLED=true");
    expect(heldVar("auto_fix_enabled", info)).toBeNull();
  });
  it("an answer without the field (an older server) holds nothing", () => {
    expect(heldVar("executor_enabled", { overridden: [] })).toBeNull();
    expect(heldVar("executor_enabled", undefined)).toBeNull();
    expect(sourceOf("executor_enabled", { overridden: ["executor_enabled"] })).toBe("stored");
  });
  it("a held switch cannot be staged", () => {
    const now = saved({ executor_enabled: false });
    expect(stage(now, {}, "executor_enabled", true, info)).toEqual({});
    expect(stage(now, { auto_fix_enabled: true }, "executor_enabled", true, info)).toEqual({ auto_fix_enabled: true });
    expect(stage(now, {}, "auto_fix_enabled", true, info)).toEqual({ auto_fix_enabled: true });
  });
});

describe("the confirmation switch says what it does today (MVP-2.9.0 N27, review)", () => {
  it("in both languages: there is no place to confirm yet, so a run stops there and ends", async () => {
    const en = (await import("@/locales/en.json")).default as Record<string, string>;
    const zh = (await import("@/locales/zh.json")).default as Record<string, string>;
    expect(en["settings.high.executor_hitl_enabled.desc"]).toMatch(/no place to (give|confirm)/i);
    expect(en["settings.high.executor_hitl_enabled.onMeans"]).toMatch(/ends as failed/i);
    expect(zh["settings.high.executor_hitl_enabled.desc"]).toContain("还没有");
    expect(zh["settings.high.executor_hitl_enabled.onMeans"]).toContain("以失败结束");
  });
});
