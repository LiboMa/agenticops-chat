import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { itemViews, loginError, needsSetup, patrolDraft, settingsTab } from "@/lib/setup";
import type { Readiness } from "@/api/types";

const check = (ok: boolean, detail = "") => ({ ok, detail, checked_at: "2026-11-19T09:03:00Z", checked_by: "user:root" });
const ready = (o: Partial<Readiness> = {}): Readiness => ({
  accounts: { state: "connected", enabled: 1, regions: 2, items: [{ id: 1, name: "prod", provider: "aws", regions: 2, check: check(true) }] },
  model: { state: "verified", model_id: "global.anthropic.claude-opus-5-5", region: "us-east-1", check: check(true) },
  execution: { state: "manual", executor_enabled: false, auto_fix_enabled: false, auto_approve_l0_l1: false, rbac_enforce: false,
               change_auto_approve_standard: false, you_can_approve: true, read_only: false },
  notifications: { state: "optional", channels: 0 },
  can_verify: true, generated_at: "2026-11-19T09:04:00Z", ...o,
});

describe("what the sign-in page says when signing in fails", () => {
  it("a wrong name or password is said as that", () => {
    expect(loginError(new ApiError(401, "Invalid credentials"))).toEqual({ key: "login.invalid", message: null });
  });
  it("a server that is down or unreachable is «unavailable», not «wrong password»", () => {
    expect(loginError(new ApiError(500, "Internal Server Error"))).toEqual({ key: "login.unavailable", message: null });
    expect(loginError(new ApiError(503, "x"))).toEqual({ key: "login.unavailable", message: null });
    expect(loginError(new TypeError("Failed to fetch"))).toEqual({ key: "login.unavailable", message: null });
  });
  it("anything else the server said is shown as it said it", () => {
    expect(loginError(new ApiError(403, "This account is disabled"))).toEqual({ key: null, message: "This account is disabled" });
    expect(loginError(new ApiError(429, ""))).toEqual({ key: "login.failed", message: null });
    expect(loginError("nope")).toEqual({ key: "login.failed", message: null });
  });
});

describe("the four items of the setup overview", () => {
  it("in this order, each with its state word and its way on", () => {
    expect(itemViews(ready()).map((v) => [v.id, v.stateKey, v.tone, v.next?.to ?? null])).toEqual([
      ["accounts", "setup.state.connected", "ok", "/app/settings?tab=accounts"],
      ["model", "setup.state.verified", "ok", "/app/settings#settings-models"],
      ["execution", "setup.state.manual", "info", "/app/settings#settings-automation"],
      ["notifications", "setup.state.optional", "neutral", "/app/settings?tab=messaging"],
    ]);
  });
  it("configured is not verified", () => {
    const v = itemViews(ready({
      accounts: { state: "configured", enabled: 2, regions: 3, items: [] },
      model: { state: "configured", model_id: "m", region: "us-east-1", check: null },
    }));
    expect(v.slice(0, 2).map((x) => [x.stateKey, x.tone])).toEqual([["setup.state.pending", "warn"], ["setup.state.pending", "warn"]]);
  });
  it("a failed check and no account at all are said in red", () => {
    const v = itemViews(ready({
      accounts: { state: "missing", enabled: 0, regions: 0, items: [] },
      model: { state: "failed", model_id: "m", region: "us-east-1", check: check(false, "AccessDeniedException (Converse)") },
    }));
    expect(v.slice(0, 2).map((x) => [x.stateKey, x.tone])).toEqual([["setup.state.missing", "danger"], ["setup.state.failed", "danger"]]);
  });
  it("execution: partly automatic is amber; a read-only account is told so and sent nowhere", () => {
    const auto = itemViews(ready({ execution: { ...ready().execution, state: "partly_automatic" } }))[2];
    expect([auto.stateKey, auto.tone]).toEqual(["setup.state.partly_automatic", "warn"]);
    const ro = itemViews(ready({ can_verify: false, execution: { ...ready().execution, state: "read_only", read_only: true, you_can_approve: false } }), { settings: false });
    expect([ro[2].stateKey, ro[2].tone]).toEqual(["setup.state.read_only", "neutral"]);
    expect(ro.map((x) => x.next)).toEqual([null, null, null, null]);      // no Settings for this person: «ask an administrator»
  });
  it("a step is owed only where an account or the model is not checked — never for a choice", () => {
    expect(itemViews(ready()).map((v) => v.owed)).toEqual([false, false, false, false]);
    const v = itemViews(ready({
      accounts: { state: "configured", enabled: 2, regions: 3, items: [] },
      model: { state: "failed", model_id: "m", region: "us-east-1", check: check(false) },
      execution: { ...ready().execution, state: "partly_automatic" },          // amber, and nobody's to-do
    }));
    expect(v.map((x) => x.owed)).toEqual([true, true, false, false]);
    expect(itemViews(ready({ accounts: { state: "missing", enabled: 0, regions: 0, items: [] } }))[0].owed).toBe(true);
  });
  it("only an administrator is offered the model verification", () => {
    expect(itemViews(ready())[1].canVerify).toBe(true);
    expect(itemViews(ready({ can_verify: false }))[1].canVerify).toBe(false);
    expect(itemViews(ready())[0].canVerify).toBe(false);
  });
});

describe("who is sent to the overview from /app", () => {
  it("an administrator of an installation with no enabled account", () => {
    expect(needsSetup(true, ready({ accounts: { state: "missing", enabled: 0, regions: 0, items: [] } }))).toBe(true);
  });
  it("nobody else, and nobody when the answer is not known", () => {
    expect(needsSetup(true, ready())).toBe(false);
    expect(needsSetup(false, ready({ accounts: { state: "missing", enabled: 0, regions: 0, items: [] } }))).toBe(false);
    expect(needsSetup(true, undefined)).toBe(false);
  });
});

describe("the Settings tab named in an address", () => {
  it("is one of the page's tabs, else the first", () => {
    expect(settingsTab("accounts")).toBe("accounts");
    expect(settingsTab("messaging")).toBe("messaging");
    expect(settingsTab("providers")).toBe("providers");                // MVP-2.9.0 N35
    expect(settingsTab("nope")).toBe("general");
    expect(settingsTab(null)).toBe("general");
  });
});

describe("«try a read-only patrol» writes a draft, it sends nothing", () => {
  const ASK = "Run a read-only patrol.";
  it("an empty new conversation gets the request", () => {
    expect(patrolDraft({ text: "", attachmentIds: [] }, ASK)).toEqual({ text: ASK, attachmentIds: [] });
  });
  it("what was already written there stays, the request after it — uploads too", () => {
    expect(patrolDraft({ text: "half a thought \n", attachmentIds: ["a1"] }, ASK))
      .toEqual({ text: `half a thought\n\n${ASK}`, attachmentIds: ["a1"] });
  });
  it("asked twice, it is there once", () => {
    const once = patrolDraft({ text: "note", attachmentIds: [] }, ASK);
    expect(patrolDraft(once, ASK)).toBe(once);
  });
});
