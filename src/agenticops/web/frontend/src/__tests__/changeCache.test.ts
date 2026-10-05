import { describe, it, expect } from "vitest";
import { changeMutationKeys, type ChangeActionArgs, type ChangeFilters } from "@/hooks/useChanges";
import { fixPlanMutationKeys } from "@/hooks/useFixPlans";
import { useUpdateSettings } from "@/hooks/useSettings";
import type { CommandAuditFilters } from "@/hooks/useCommandAudits";

// I2 — every change mutation invalidates the caches the audit tab reads, plan-stats included.
describe("changeMutationKeys (I2)", () => {
  it("invalidates changes, the detail, the timeline, fix-plans and plan-stats", () => {
    const keys = changeMutationKeys(7);
    expect(keys).toContainEqual(["changes"]);
    expect(keys).toContainEqual(["change", 7]);
    expect(keys).toContainEqual(["change-timeline", 7]);
    expect(keys).toContainEqual(["fix-plans"]);
    expect(keys).toContainEqual(["plan-stats"]);
  });
});

describe("fixPlanMutationKeys (I2)", () => {
  it("invalidates fix-plans, the detail and plan-stats", () => {
    const keys = fixPlanMutationKeys(7);
    expect(keys).toContainEqual(["fix-plans"]);
    expect(keys).toContainEqual(["fix-plan", 7]);
    expect(keys).toContainEqual(["plan-stats"]);
  });
  it("also invalidates the issue, the issues list and the issue's runs, which approve and execute move", () => {
    const keys = fixPlanMutationKeys(1);
    for (const key of [["fix-plans"], ["fix-plan", 1], ["plan-stats"], ["anomaly"], ["anomalies"], ["issue-executions"]]) {
      expect(keys).toContainEqual(key);
    }
  });
  it("also invalidates the issue timeline: an approval's move and its auto-run's start are read there (C1(c))", () => {
    expect(fixPlanMutationKeys(1)).toContainEqual(["issue-timeline"]);
  });
});

// M1 — the change-action args are a discriminated union: each action carries the body the backend expects.
describe("ChangeActionArgs is a discriminated union (M1)", () => {
  it("rejects an approve with no body at compile time", () => {
    // @ts-expect-error M1: approve requires { reason, content_hash }
    const noBody: ChangeActionArgs = { id: 1, action: "approve" };
    expect(noBody).toBeDefined();
  });
  it("rejects an approve carrying the wrong body at compile time", () => {
    // @ts-expect-error M1: approve's body is { reason, content_hash }, not { message }
    const wrongBody: ChangeActionArgs = { id: 1, action: "approve", body: { message: "x" } };
    expect(wrongBody).toBeDefined();
  });
  it("rejects an approve that does not name the plan content at compile time", () => {
    // @ts-expect-error MVP-2.6.1: approve binds to the plan content it was shown
    const noHash: ChangeActionArgs = { id: 1, action: "approve", body: { reason: "ok" } };
    expect(noHash).toBeDefined();
  });
  it("accepts the body each action expects", () => {
    const approve: ChangeActionArgs = { id: 1, action: "approve", body: { reason: "ok", content_hash: "ab12" } };
    const clarify: ChangeActionArgs = { id: 1, action: "clarify", body: { message: "why?" } };
    const resolve: ChangeActionArgs = { id: 1, action: "resolve-review", body: { outcome: "completed", reason: "verified" } };
    const execute: ChangeActionArgs = { id: 1, action: "execute" };
    expect([approve, clarify, resolve, execute]).toHaveLength(4);
  });
});

// M2 — filter unions instead of a bare string.
describe("filter fields are narrowed unions (M2)", () => {
  it("rejects a bogus change status at compile time", () => {
    // @ts-expect-error M2: status is a ChangeStatus, not an arbitrary string
    const cf: ChangeFilters = { status: "bogus" };
    expect(cf).toBeDefined();
  });
  it("rejects a bogus command-audit outcome at compile time", () => {
    // @ts-expect-error M2: outcome is CommandAudit["outcome"], not an arbitrary string
    const af: CommandAuditFilters = { outcome: "bogus" };
    expect(af).toBeDefined();
  });
});

// M6 — SettingsPatch drops the read-only flags.
type SettingsPatchArg = Parameters<ReturnType<typeof useUpdateSettings>["mutate"]>[0];
describe("SettingsPatch omits the read-only flags (M6)", () => {
  it("rejects a patch of change_management_enabled at compile time", () => {
    // @ts-expect-error M6: change_management_enabled is read-only (PATCH rejects it as an unknown key)
    const badPatch: SettingsPatchArg = { change_management_enabled: true };
    expect(badPatch).toBeDefined();
  });
});
