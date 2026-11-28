import { describe, expect, it } from "vitest";
import { draftOf, filterModels, modelPatch, priceLabel, toolsState } from "@/lib/providerModels";
import type { ProviderModel } from "@/hooks/useModelProviders";

function model(over: Partial<ProviderModel> = {}): ProviderModel {
  return {
    provider: "p", model_id: "qwen3:32b", label: "Qwen3 32B", purpose: "chat", context_window: 32768,
    max_output_tokens: null, supports_tools: null, tools_probe: null, tools_probe_at: null, supports_images: false,
    supports_documents: false, reasoning: "none", price_input: null, price_output: null, price_cache_read: null,
    price_cache_write: null, source: "discovered", enabled: true, manual_fields: [], tools: null,
    accepts_temperature: null, prompt_cache: null, ...over,
  };
}

describe("toolsState", () => {
  it("reads the server's effective answer", () => {
    expect(toolsState(model({ tools: true }))).toBe("yes");
    expect(toolsState(model({ tools: false }))).toBe("no");
    expect(toolsState(model({ tools: null }))).toBe("untested");
  });
});

describe("priceLabel", () => {
  it("says the input / output price per million tokens, or nothing when unpriced", () => {
    expect(priceLabel(model())).toBeNull();
    expect(priceLabel(model({ price_input: 3, price_output: 15 }))).toBe("$3 / $15");
    expect(priceLabel(model({ price_input: 0.15 }))).toBe("$0.15 / $0");
  });
});

describe("filterModels", () => {
  const list = [model({ model_id: "a/chat-1", label: "Alpha" }), model({ model_id: "embed-2", label: "E", purpose: "embedding" }),
                model({ model_id: "b/chat-3", label: "Beta Chat" })];
  it("filters by purpose and by a query over id and label, case-blind", () => {
    expect(filterModels(list, { purpose: "all", query: "" }).map((m) => m.model_id)).toEqual(["a/chat-1", "embed-2", "b/chat-3"]);
    expect(filterModels(list, { purpose: "embedding", query: "" }).map((m) => m.model_id)).toEqual(["embed-2"]);
    expect(filterModels(list, { purpose: "all", query: "BETA" }).map((m) => m.model_id)).toEqual(["b/chat-3"]);
    expect(filterModels(list, { purpose: "chat", query: "a/" }).map((m) => m.model_id)).toEqual(["a/chat-1"]);
  });
});

describe("modelPatch", () => {
  it("sends only what changed, with the server's types", () => {
    const m = model();
    expect(modelPatch(m, draftOf(m))).toEqual({});
    expect(modelPatch(m, { ...draftOf(m), contextWindow: "128000", tools: "yes", priceInput: "0.5" }))
      .toEqual({ context_window: 128000, supports_tools: true, price_input: 0.5 });
    expect(modelPatch(model({ supports_tools: true }), { ...draftOf(model({ supports_tools: true })), tools: "unknown" }))
      .toEqual({ supports_tools: null });
    expect(modelPatch(m, { ...draftOf(m), contextWindow: "" })).toEqual({ context_window: null });
    expect(modelPatch(m, { ...draftOf(m), label: " New ", reasoning: "openai_effort", images: true }))
      .toEqual({ label: "New", reasoning: "openai_effort", supports_images: true });
  });
  it("names the field it cannot send", () => {
    const m = model();
    expect(modelPatch(m, { ...draftOf(m), contextWindow: "0" })).toEqual({ error: "contextWindow" });
    expect(modelPatch(m, { ...draftOf(m), maxOutput: "1.5" })).toEqual({ error: "maxOutput" });
    expect(modelPatch(m, { ...draftOf(m), priceOutput: "-1" })).toEqual({ error: "priceOutput" });
    expect(modelPatch(m, { ...draftOf(m), priceCacheRead: "abc" })).toEqual({ error: "priceCacheRead" });
  });
});


// ── what a request may carry: the row's word, never the model's name (review of MVP-2.9.0, Standards 1) ─────
describe("temperature and prompt cache", () => {
  it("reads «not said» as its own choice", () => {
    expect(draftOf(model())).toMatchObject({ temperature: "unknown", promptCache: "default" });
    expect(draftOf(model({ accepts_temperature: true, prompt_cache: false })))
      .toMatchObject({ temperature: "yes", promptCache: "off" });
  });
  it("sends yes / no / null, and only when changed", () => {
    const m = model();
    expect(modelPatch(m, { ...draftOf(m), temperature: "yes", promptCache: "on" }))
      .toEqual({ accepts_temperature: true, prompt_cache: true });
    const set = model({ accepts_temperature: false, prompt_cache: true });
    expect(modelPatch(set, draftOf(set))).toEqual({});
    expect(modelPatch(set, { ...draftOf(set), temperature: "unknown", promptCache: "default" }))
      .toEqual({ accepts_temperature: null, prompt_cache: null });
  });
});
