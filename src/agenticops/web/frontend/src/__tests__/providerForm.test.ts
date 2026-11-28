import { describe, expect, it } from "vitest";
import {
  MASK, createBody, emptyForm, testNotes, formFromRow, headersFromText, headersToText, patchFromForm, validateProviderForm,
  type ProviderForm, type ProviderRowLike,
} from "@/lib/providerForm";

const preset = { preset: "litellm_proxy", kind: "openai_compatible" as const, base_url: "http://localhost:4000/v1", needs_key: true };
const ollama = { preset: "ollama", kind: "openai_compatible" as const, base_url: "http://localhost:11434/v1", needs_key: false };

function form(over: Partial<ProviderForm> = {}): ProviderForm {
  return { ...emptyForm(preset), name: "local-llm", apiKey: "sk-1", ...over };
}

describe("emptyForm", () => {
  it("starts from the preset's address and protocol", () => {
    const f = emptyForm(preset);
    expect(f).toMatchObject({ preset: "litellm_proxy", kind: "openai_compatible", baseUrl: "http://localhost:4000/v1",
                              timeout: "60", name: "", apiKey: "", headersText: "" });
  });
});

describe("validateProviderForm", () => {
  it("accepts a good form", () => {
    expect(validateProviderForm(form(), { isNew: true, needsKey: true, hasStoredKey: false })).toBeNull();
  });
  it("follows the server's name rule", () => {
    for (const name of ["", "a", "Local", "1abc", "local_llm", "x".repeat(33), "has space"]) {
      expect(validateProviderForm(form({ name }), { isNew: true, needsKey: true, hasStoredKey: false }))
        .toEqual({ field: "name", reason: "name" });
    }
    expect(validateProviderForm(form({ name: "ab" }), { isNew: true, needsKey: true, hasStoredKey: false })).toBeNull();
    expect(validateProviderForm(form({ name: "bedrock" }), { isNew: true, needsKey: true, hasStoredKey: false }))
      .toEqual({ field: "name", reason: "nameReserved" });
  });
  it("does not check the name of a provider being edited (it cannot change)", () => {
    expect(validateProviderForm(form({ name: "Old_Name" }), { isNew: false, needsKey: true, hasStoredKey: true })).toBeNull();
  });
  it("wants an http(s) address with a host", () => {
    for (const baseUrl of ["", "localhost:4000", "ftp://h/v1", "http://", "  "]) {
      expect(validateProviderForm(form({ baseUrl }), { isNew: true, needsKey: true, hasStoredKey: false }))
        .toEqual({ field: "baseUrl", reason: "baseUrl" });
    }
    expect(validateProviderForm(form({ baseUrl: " https://openrouter.ai/api/v1/ " }), { isNew: true, needsKey: true, hasStoredKey: false })).toBeNull();
  });
  it("wants a key only where the platform needs one and none is stored", () => {
    expect(validateProviderForm(form({ apiKey: "" }), { isNew: true, needsKey: true, hasStoredKey: false }))
      .toEqual({ field: "apiKey", reason: "apiKey" });
    expect(validateProviderForm(form({ apiKey: " " }), { isNew: true, needsKey: true, hasStoredKey: false }))
      .toEqual({ field: "apiKey", reason: "apiKey" });
    expect(validateProviderForm(form({ apiKey: "" }), { isNew: true, needsKey: false, hasStoredKey: false })).toBeNull();
    expect(validateProviderForm(form({ apiKey: "" }), { isNew: false, needsKey: true, hasStoredKey: true })).toBeNull();
  });
  it("checks the headers and the timeout", () => {
    expect(validateProviderForm(form({ headersText: "X-Title ops" }), { isNew: true, needsKey: true, hasStoredKey: false }))
      .toEqual({ field: "headers", reason: "headers" });
    for (const timeout of ["4", "601", "abc", "", "10.5"]) {
      expect(validateProviderForm(form({ timeout }), { isNew: true, needsKey: true, hasStoredKey: false }))
        .toEqual({ field: "timeout", reason: "timeout" });
    }
    expect(validateProviderForm(form({ timeout: "600" }), { isNew: true, needsKey: true, hasStoredKey: false })).toBeNull();
  });
});

describe("headersFromText", () => {
  it("reads one «Name: value» per line, at the first colon", () => {
    expect(headersFromText("X-Title: ops\n\nHTTP-Referer: https://ops.example.com/x\n")).toEqual({
      headers: { "X-Title": "ops", "HTTP-Referer": "https://ops.example.com/x" } });
    expect(headersFromText("")).toEqual({ headers: {} });
  });
  it("says which line is wrong", () => {
    expect(headersFromText("X-Title: ops\nno colon here")).toEqual({ error: { line: 2 } });
    expect(headersFromText(": value")).toEqual({ error: { line: 1 } });
    expect(headersFromText("Bad Name: v")).toEqual({ error: { line: 1 } });
  });
  it("round-trips a stored header as its mask", () => {
    expect(headersToText(["X-B", "X-A"])).toBe(`X-B: ${MASK}\nX-A: ${MASK}`);
    expect(headersFromText(headersToText(["X-A"]))).toEqual({ headers: { "X-A": MASK } });
  });
});

const row: ProviderRowLike = {
  name: "local-llm", display_name: "Local", kind: "openai_compatible", preset: "litellm_proxy",
  base_url: "http://h:4000/v1", timeout_seconds: 60, header_names: ["X-Title"], has_api_key: true,
};

describe("createBody", () => {
  it("sends what was typed, trimmed; no key when none was typed", () => {
    expect(createBody(form({ displayName: " Local ", baseUrl: " http://h:4000/v1/ ", headersText: "X-Title: ops" }))).toEqual({
      name: "local-llm", display_name: "Local", preset: "litellm_proxy", kind: "openai_compatible",
      base_url: "http://h:4000/v1", api_key: "sk-1", extra_headers: { "X-Title": "ops" }, timeout_seconds: 60 });
    const body = createBody({ ...emptyForm(ollama), name: "ollama" });
    expect(body).not.toHaveProperty("api_key");
    expect(body.display_name).toBe("ollama");
  });
});

describe("patchFromForm", () => {
  it("sends only what changed, and never an empty key", () => {
    const f = formFromRow(row);
    expect(f.apiKey).toBe("");
    expect(f.headersText).toBe(`X-Title: ${MASK}`);
    expect(patchFromForm(row, f)).toEqual({});
    expect(patchFromForm(row, { ...f, timeout: "90" })).toEqual({ timeout_seconds: 90 });
    expect(patchFromForm(row, { ...f, apiKey: "sk-new" })).toEqual({ api_key: "sk-new" });
    expect(patchFromForm(row, { ...f, baseUrl: "http://h:4000/v1/" })).toEqual({});           // the same address
    expect(patchFromForm(row, { ...f, headersText: `X-Title: ${MASK}\nX-Env: prod` }))
      .toEqual({ extra_headers: { "X-Title": MASK, "X-Env": "prod" } });
    expect(patchFromForm(row, { ...f, headersText: "" })).toEqual({ extra_headers: {} });
  });
  it("asks to remove the stored key only when told to", () => {
    expect(patchFromForm(row, formFromRow(row), { clearKey: true })).toEqual({ clear_api_key: true });
  });
});

describe("the model list of a provider just saved (N35 E2E: «Save and test» read the list of provider «»)", () => {
  it("a request path never names an empty provider", async () => {
    const { modelsPath } = await import("@/hooks/useModelProviders");
    expect(modelsPath("litellm-openai", "refresh-models")).toBe("/model-providers/litellm-openai/refresh-models");
    expect(() => modelsPath("", "refresh-models")).toThrow();
    expect(() => modelsPath("  ", "models")).toThrow();
  });
  it("the dialog hands the saved name to the refresh, not the name it was opened with", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const dialog = readFileSync(resolve(__dirname, "../components/settings/ProviderDialog.tsx"), "utf8");
    expect(dialog).toMatch(/refresh\.mutateAsync\(name\)/);
    expect(dialog).not.toMatch(/refresh\.mutateAsync\(\)/);
  });
});

describe("the providers table on a phone (N35 E2E: the page was 634 px wide in a 390 px window)", () => {
  it("its scroll box is a positioned box, so the screen-reader-only labels inside cannot widen the page", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const tab = readFileSync(resolve(__dirname, "../components/settings/ModelProvidersTab.tsx"), "utf8");
    const wrapper = /<div className="([^"]*)">\s*<table/.exec(tab)?.[1] ?? "";
    expect(wrapper).toMatch(/\boverflow-x-auto\b/);
    expect(wrapper).toMatch(/\brelative\b/);
    expect(tab).toMatch(/sr-only/);                      // the reason it must be positioned
  });
});

describe("testNotes (final review: «no model yet» hid why the list could not be read)", () => {
  it("keeps the list's failure beside the test's", () => {
    expect(testNotes("authentication failed (401)", { code: "no_model", message: "x" })).toEqual([
      { key: "settings.providers.listFailed", error: "authentication failed (401)" },
      { key: "settings.providers.noModelYet" }]);
    expect(testNotes(null, { code: "no_model", message: "x" })).toEqual([{ key: "settings.providers.noModelYet" }]);
    expect(testNotes(null, { code: "boom", message: "it broke" })).toEqual([{ text: "it broke" }]);
    expect(testNotes("timed out", null)).toEqual([{ key: "settings.providers.listFailed", error: "timed out" }]);
    expect(testNotes(null, null)).toEqual([]);
  });
});

describe("a writer's agent model controls (final review: they stayed enabled and every change was a 403)", () => {
  it("max tokens, the window and reset are an administrator's, like the model", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const page = readFileSync(resolve(__dirname, "../pages/Settings.tsx"), "utf8");
    const card = page.slice(page.indexOf("function AgentModelsCard"), page.indexOf("function GalaxyModelCard"));
    const disabled = card.match(/disabled=\{[^}]*\}/g) ?? [];
    expect(disabled.length).toBeGreaterThanOrEqual(5);
    for (const d of disabled) expect(d).toMatch(/!canChange/);
  });
});

describe("the page says where conversations go (the spec: «页面上写明数据会发给这家»)", () => {
  it("the providers tab and the add dialog carry the notice, in both languages", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const tab = readFileSync(resolve(__dirname, "../components/settings/ModelProvidersTab.tsx"), "utf8");
    const dialog = readFileSync(resolve(__dirname, "../components/settings/ProviderDialog.tsx"), "utf8");
    expect(tab).toMatch(/settings\.providers\.dataNotice/);
    expect(dialog).toMatch(/settings\.providers\.dataNotice/);
    for (const lang of ["en", "zh"]) {
      const words = JSON.parse(readFileSync(resolve(__dirname, `../locales/${lang}.json`), "utf8"));
      expect(words["settings.providers.dataNotice"]).toBeTruthy();
    }
  });
});

// ── test before save (MVP-2.9.0 review, Spec ③) ──────────────────────────────────────────────────────────────
import { connectionChanged, connectionKey, draftBody, saveMode } from "@/lib/providerForm";

const stored: ProviderRowLike = {
  name: "local-llm", display_name: "Local", kind: "openai_compatible", preset: "litellm_proxy",
  base_url: "http://localhost:4000/v1", timeout_seconds: 60, header_names: ["X-Org"], has_api_key: true,
};
const step = (ok: boolean) => ({ ok, ms: 1, error: ok ? null : "refused" });
const result = (list: boolean, chat: boolean, tools: boolean) =>
  ({ model_id: "m", at: "2026-11-26T00:00:00Z", list: step(list), chat: step(chat), tools: step(tools) });

describe("connectionChanged", () => {
  it("a new provider is always a new connection", () => {
    expect(connectionChanged(null, form(), false)).toBe(true);
  });
  it("an edit of the display name or the timeout is not", () => {
    expect(connectionChanged(stored, { ...formFromRow(stored), displayName: "Other", timeout: "90" }, false)).toBe(false);
  });
  it("an edit of the address, the protocol, the key or the headers is", () => {
    const base = formFromRow(stored);
    expect(connectionChanged(stored, { ...base, baseUrl: "http://other:4000/v1" }, false)).toBe(true);
    expect(connectionChanged(stored, { ...base, kind: "anthropic_compatible" }, false)).toBe(true);
    expect(connectionChanged(stored, { ...base, apiKey: "sk-new" }, false)).toBe(true);
    expect(connectionChanged(stored, { ...base, headersText: `X-Org: ${MASK}\nX-Team: ops` }, false)).toBe(true);
    expect(connectionChanged(stored, base, true)).toBe(true);                    // removing the stored key
  });
  it("a trailing slash or spaces are no change", () => {
    expect(connectionChanged(stored, { ...formFromRow(stored), baseUrl: " http://localhost:4000/v1/ " }, false)).toBe(false);
  });
});

describe("saveMode", () => {
  const f = form();
  const key = connectionKey(f, false);
  it("an edit that leaves the connection alone saves without a test", () => {
    expect(saveMode({ changed: false, testedKey: null, currentKey: key, result: null })).toBe("save_plain");
  });
  it("a new connection is tested first", () => {
    expect(saveMode({ changed: true, testedKey: null, currentKey: key, result: null })).toBe("needs_test");
  });
  it("list and chat passed: save — a failed tool call only warns", () => {
    expect(saveMode({ changed: true, testedKey: key, currentKey: key, result: result(true, true, true) })).toBe("save");
    expect(saveMode({ changed: true, testedKey: key, currentKey: key, result: result(true, true, false) })).toBe("save");
  });
  it("the test failed: it can only be stored switched off", () => {
    expect(saveMode({ changed: true, testedKey: key, currentKey: key, result: result(false, false, false) })).toBe("save_disabled");
    expect(saveMode({ changed: true, testedKey: key, currentKey: key, result: result(true, false, false) })).toBe("save_disabled");
  });
  it("a test of an earlier form does not count", () => {
    const later = connectionKey(form({ apiKey: "sk-2" }), false);
    expect(saveMode({ changed: true, testedKey: key, currentKey: later, result: result(true, true, true) })).toBe("needs_test");
  });
});

describe("draftBody", () => {
  it("a new provider: the create body and the model to try", () => {
    expect(draftBody(form(), null, { clearKey: false, modelId: "qwen3:32b" })).toEqual({ ...createBody(form()), model_id: "qwen3:32b" });
  });
  it("an edit: the stored provider and what changed — an empty key field keeps the stored key", () => {
    const f = { ...formFromRow(stored), baseUrl: "http://other:4000/v1" };
    expect(draftBody(f, stored, { clearKey: false, modelId: "" }))
      .toEqual({ provider: "local-llm", base_url: "http://other:4000/v1" });
  });
});
