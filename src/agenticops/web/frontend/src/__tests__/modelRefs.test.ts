import { describe, expect, it } from "vitest";
import { badges, groupPresets, issueOf, parseRef, type ModelPreset } from "@/lib/modelRefs";

const caps = (tools: boolean | null, images = false, documents = false, reasoning = "none") =>
  ({ tools, images, documents, reasoning });

const P: ModelPreset[] = [
  { label: "Opus 5.5", value: "global.anthropic.claude-opus-5-5", provider: "bedrock", provider_label: "Amazon Bedrock",
    purpose: "chat", capabilities: caps(true, true, true, "anthropic_thinking"), priced: true },
  { label: "Qwen3 32B", value: "ollama::qwen3:32b", provider: "ollama", provider_label: "Ollama", purpose: "chat",
    capabilities: caps(null), priced: false },
  { label: "Llama Tiny", value: "ollama::llama-tiny", provider: "ollama", provider_label: "Ollama", purpose: "chat",
    capabilities: caps(false), priced: false },
  { label: "Claude Sonnet", value: "litellm::anthropic/claude-sonnet", provider: "litellm", provider_label: "LiteLLM",
    purpose: "chat", capabilities: caps(true, true, false), priced: true },
  { label: "Embed", value: "litellm::text-embed", provider: "litellm", provider_label: "LiteLLM", purpose: "embedding",
    capabilities: caps(false), priced: true },
  { label: "Haiku 4.5", value: "global.anthropic.claude-haiku-4-5-20251001-v1:0" },          // an older server's shape
];

describe("parseRef", () => {
  it("splits at the first «::», as the server does", () => {
    expect(parseRef("global.anthropic.claude-opus-5-5")).toEqual({ provider: null, model: "global.anthropic.claude-opus-5-5" });
    expect(parseRef("ollama-local::qwen3:32b")).toEqual({ provider: "ollama-local", model: "qwen3:32b" });
    expect(parseRef("p1::a::b")).toEqual({ provider: "p1", model: "a::b" });       // the server's own example
  });
  it("refuses what the server refuses", () => {
    for (const bad of ["::x", "P!::x", "p1::", "p::a::b", "bedrock::x", ""]) expect(parseRef(bad)).toBeNull();   // one letter is no name
  });
});

describe("groupPresets", () => {
  it("puts Bedrock first, then the providers by name; keeps each group's order; chat by default", () => {
    const groups = groupPresets(P, { query: "" });
    expect(groups.map((g) => g.provider)).toEqual(["bedrock", "litellm", "ollama"]);
    expect(groups[0].label).toBe("Amazon Bedrock");
    expect(groups[0].items.map((p) => p.value)).toEqual(["global.anthropic.claude-opus-5-5",
                                                         "global.anthropic.claude-haiku-4-5-20251001-v1:0"]);
    expect(groups[2].items.map((p) => p.label)).toEqual(["Qwen3 32B", "Llama Tiny"]);
  });
  it("lists embedding models when asked", () => {
    expect(groupPresets(P, { query: "", purpose: "embedding" }).flatMap((g) => g.items.map((p) => p.value)))
      .toEqual(["litellm::text-embed"]);
  });
  it("searches label, id and provider, case-blind", () => {
    const values = (q: string) => groupPresets(P, { query: q }).flatMap((g) => g.items.map((p) => p.value));
    expect(values("QWEN")).toEqual(["ollama::qwen3:32b"]);
    expect(values("anthropic/")).toEqual(["litellm::anthropic/claude-sonnet"]);
    expect(values("ollama")).toEqual(["ollama::qwen3:32b", "ollama::llama-tiny"]);
    expect(values("amazon")).toHaveLength(2);
    expect(values("nothing-like-it")).toEqual([]);
  });
});

describe("badges", () => {
  it("says what the model can do, and when it is not priced", () => {
    expect(badges(P[0])).toEqual(["tools", "images", "documents", "reasoning"]);
    expect(badges(P[1])).toEqual(["toolsUnknown", "unpriced"]);
    expect(badges(P[2])).toEqual(["noTools", "unpriced"]);
    expect(badges(P[3])).toEqual(["tools", "images"]);
    expect(badges(P[5])).toEqual([]);                                  // no capabilities known: nothing claimed
  });
});

describe("issueOf", () => {
  const issues = [{ setting: "agent_main_model_id", value: "gone::m", reason: "unknown_provider" }];
  it("is «unavailable» when the server lists the setting, or a provider model is not on the list", () => {
    expect(issueOf("gone::m", P, issues, "agent_main_model_id")).toBe("unavailable");
    expect(issueOf("ollama::not-listed", P, [], "agent_rca_model_id")).toBe("unavailable");
  });
  it("is «noTools» when the model is listed as calling no tools", () => {
    expect(issueOf("ollama::llama-tiny", P, [], "agent_rca_model_id")).toBe("noTools");
  });
  it("is nothing otherwise — a Bedrock id off the list is the picker's own «not on the list»", () => {
    expect(issueOf("ollama::qwen3:32b", P, [], "agent_rca_model_id")).toBeNull();
    expect(issueOf("global.anthropic.claude-custom", P, [], "agent_rca_model_id")).toBeNull();
    expect(issueOf("", P, [], "galaxy_model_id")).toBeNull();
    expect(issueOf("gone::m", P, issues, "agent_rca_model_id")).toBe("unavailable");       // not on the list either
  });
});
