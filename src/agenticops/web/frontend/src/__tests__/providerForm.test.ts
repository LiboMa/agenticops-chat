import { describe, expect, it } from "vitest";
import {
  MASK, createBody, emptyForm, formFromRow, headersFromText, headersToText, patchFromForm, validateProviderForm,
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
