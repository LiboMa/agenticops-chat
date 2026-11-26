"""Platform presets (MVP-2.9.0 N35): the protocol, the usual address and whether a key is needed, so an admin only fills
in what differs. Two protocols cover every named platform: OpenAI-compatible (Chat Completions) and Anthropic-compatible
(Messages)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

OPENAI = "openai_compatible"
ANTHROPIC = "anthropic_compatible"
KINDS = (OPENAI, ANTHROPIC)


def default_preset(kind) -> str:
    """The preset of a provider added without one: the «Other» preset of its protocol (OpenAI-compatible unless it
    says Anthropic)."""
    return "custom_anthropic" if kind == ANTHROPIC else "custom_openai"


@dataclass(frozen=True)
class Preset:
    kind: str
    base_url: str
    needs_key: bool
    label: str
    notes: str


PRESETS: dict[str, Preset] = {
    "litellm_proxy": Preset(OPENAI, "http://localhost:4000/v1", True, "LiteLLM proxy",
                            "The proxy's virtual or master key; model ids are the proxy's model names."),
    "openrouter": Preset(OPENAI, "https://openrouter.ai/api/v1", True, "OpenRouter",
                         "An OpenRouter key; its model list carries prices, context lengths and tool support."),
    "vllm": Preset(OPENAI, "http://localhost:8000/v1", False, "vLLM",
                   "vLLM's OpenAI-compatible server; a key only if it was started with --api-key. Tool calls need "
                   "--enable-auto-tool-choice and a tool parser."),
    "ollama": Preset(OPENAI, "http://localhost:11434/v1", False, "Ollama",
                     "Ollama's OpenAI-compatible endpoint; no key. Only models with tool support can run agents."),
    "lmstudio": Preset(OPENAI, "http://localhost:1234/v1", False, "LM Studio", "LM Studio's local server; no key."),
    "sub2api": Preset(ANTHROPIC, "", True, "Sub2API",
                      "The gateway's address (its Anthropic Messages endpoint) and a key it issued."),
    "anthropic": Preset(ANTHROPIC, "https://api.anthropic.com", True, "Anthropic", "An Anthropic API key."),
    "custom_openai": Preset(OPENAI, "", False, "Other (OpenAI-compatible)",
                            "Any server that speaks the OpenAI Chat Completions API."),
    "custom_anthropic": Preset(ANTHROPIC, "", False, "Other (Anthropic-compatible)",
                               "Any server that speaks the Anthropic Messages API."),
}


def public() -> list[dict]:
    return [{"preset": key, **asdict(p)} for key, p in PRESETS.items()]

# Anthropic-compatible platforms that speak Anthropic's own API, prompt caching included: a model of theirs gets the
# cache unless its row says otherwise. Any other gateway gets it only when its row says so (review of MVP-2.9.0:
# the cache used to follow «claude» in the model's name).
PROMPT_CACHE_PRESETS = frozenset({"anthropic", "sub2api"})
