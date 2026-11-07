#!/usr/bin/env python
"""Live Strands smoke test against real Bedrock — opt-in, never run by pytest (a few cents per model).

The unit suite mocks `Agent` / `BedrockModel` almost everywhere, so an SDK upgrade is proven here instead. For each
distinct model id the committed settings give the agents (plus the cheap tier), it builds an agent exactly the way the
agent modules do (our conversation manager, context plugins and `bedrock_model_kwargs`) and checks:

  build     the agent builds with zero warnings (no "ignoring co-provided conversation_manager", no deprecations)
  window    the conversation manager is ours (sliding window size / Null), not replaced by the SDK
  stream    a tool call streams `current_tool_use`, the tool result and `result`
  cache     a second, fresh agent with the same prefix reads from the prompt cache (Anthropic models only)
  thinking  the request carrying the model's thinking shape is accepted (adaptive / budget_tokens / reasoning_effort)
  limits    `limits={"turns": 1}` (how the RCA caps its loop) is accepted and returns
and once, without a model call: `activate_skill` registers a skill's declared tools on a live agent.

Usage:  PYTHONPATH=src python scripts/smoke/strands_live_smoke.py [--models id1,id2] [--skip-thinking]
Exit code 1 when any check fails.
"""
from __future__ import annotations

import argparse
import sys
import warnings

FILLER = ("You are a careful operations assistant. Answer briefly. " * 500).strip()  # ~11k tokens: Opus 4.6 /
# Haiku 4.5 cache nothing at ~4.4k tokens (measured 2026-11-06 on Strands 1.45 AND 1.64 — a model-side minimum), fine at ~11k
SYSTEM_PROMPT = FILLER + "\n\nWhen asked to echo, call the echo tool exactly once and reply with its output only."
AGENT_FOR_TIER = "main"  # whose conversation manager / plugins a model is built with when no agent maps to it


def echo_tool():
    from strands import tool

    @tool
    def echo(text: str) -> str:
        """Return the given text unchanged.

        Args:
            text: Text to echo.
        """
        return f"echo:{text}"

    return echo


def model_ids() -> dict[str, str]:
    """model id → the agent whose settings build it (first agent that uses it)."""
    from agenticops.config import AGENT_NAMES, get_agent_model_config, settings
    out: dict[str, str] = {}
    for name in AGENT_NAMES:
        mid, _ = get_agent_model_config(name)
        out.setdefault(mid, name)
    out.setdefault(settings.bedrock_model_id_cheap, AGENT_FOR_TIER)
    return out


def build_agent(model_id: str, agent_name: str, thinking: bool):
    from strands import Agent
    from strands.models.bedrock import BedrockModel

    from agenticops.agents.preamble import bedrock_model_kwargs, is_anthropic_model, thinking_fields_for_budget
    from agenticops.config import get_agent_context_plugins, get_agent_conversation_manager, get_bedrock_boto_session

    max_tokens = 4096
    fields = thinking_fields_for_budget(2048, max_tokens, model_id) if thinking else None
    model = BedrockModel(model_id=model_id, boto_session=get_bedrock_boto_session(), max_tokens=max_tokens,
                         **bedrock_model_kwargs(model_id, fields))
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=model, tools=[echo_tool()], callback_handler=None,
                  conversation_manager=get_agent_conversation_manager(agent_name),
                  plugins=get_agent_context_plugins(agent_name))
    return agent, is_anthropic_model(model_id)


async def stream_once(agent, prompt: str, **kw) -> tuple[set[str], object]:
    seen: set[str] = set()
    result = None
    async for event in agent.stream_async(prompt, **kw):
        if not isinstance(event, dict):
            continue
        for key in ("data", "current_tool_use", "result"):
            if key in event:
                seen.add(key)
        msg = event.get("message")
        if isinstance(msg, dict) and any("toolResult" in c for c in msg.get("content", []) if isinstance(c, dict)):
            seen.add("toolResult")
        if "result" in event:
            result = event["result"]
    return seen, result


def usage(result) -> dict:
    try:
        return dict(result.metrics.accumulated_usage)
    except Exception:
        return {}


def check_model(model_id: str, agent_name: str, thinking: bool) -> dict[str, str]:
    import asyncio

    from agenticops.config import FULL_CONTEXT, get_agent_window_size
    row: dict[str, str] = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            agent, anthropic = build_agent(model_id, agent_name, thinking)
        row["build"] = "ok"
    except Exception as e:  # noqa: BLE001 — report every failure, keep going
        return {"build": f"FAIL {type(e).__name__}: {e}"[:160]}

    cm = agent.conversation_manager
    want = get_agent_window_size(agent_name)
    got = getattr(cm, "window_size", None)
    ok = (type(cm).__name__ == "NullConversationManager") if want == FULL_CONTEXT else (got == want)
    row["window"] = "ok" if ok else f"FAIL {type(cm).__name__} window={got} want={want}"

    try:
        seen, result = asyncio.run(stream_once(agent, "Please echo the word ping."))
        missing = {"data", "current_tool_use", "toolResult", "result"} - seen
        row["stream"] = "ok" if not missing else f"FAIL missing {sorted(missing)}"
        row["thinking"] = "ok" if thinking else "skipped"
    except Exception as e:  # noqa: BLE001
        row["stream"] = f"FAIL {type(e).__name__}: {e}"[:160]
        row["thinking"] = "FAIL (see stream)" if thinking else "skipped"

    if anthropic:
        try:
            fresh, _ = build_agent(model_id, agent_name, thinking)
            _, res2 = asyncio.run(stream_once(fresh, "Please echo the word pong."))
            read = usage(res2).get("cacheReadInputTokens", 0)
            row["cache"] = f"ok (read {read})" if read > 0 else f"FAIL cacheReadInputTokens={read}"
        except Exception as e:  # noqa: BLE001
            row["cache"] = f"FAIL {type(e).__name__}: {e}"[:160]
    else:
        row["cache"] = "n/a (not Anthropic)"

    try:
        lim, _ = build_agent(model_id, agent_name, thinking)
        asyncio.run(stream_once(lim, "Please echo the word turn.", limits={"turns": 1}))
        row["limits"] = "ok"
    except Exception as e:  # noqa: BLE001
        row["limits"] = f"FAIL {type(e).__name__}: {e}"[:160]
    return row


def check_skill_activation() -> str:
    """activate_skill registers the skill's declared tools on a live agent (no model call: direct tool use)."""
    from strands import Agent
    from strands.models.bedrock import BedrockModel

    from agenticops.config import get_bedrock_boto_session, settings
    from agenticops.skills.tools import activate_skill
    try:
        agent = Agent(model=BedrockModel(model_id=settings.bedrock_model_id_cheap, boto_session=get_bedrock_boto_session()),
                      tools=[activate_skill], callback_handler=None)
        agent.tool.activate_skill(skill_name="web-research", record_direct_tool_call=False)
        names = set(agent.tool_registry.registry)
        want = {"web_search", "web_fetch"}
        return "ok" if want <= names else f"FAIL registry lacks {sorted(want - names)}"
    except Exception as e:  # noqa: BLE001
        return f"FAIL {type(e).__name__}: {e}"[:160]


def main() -> int:
    import importlib.metadata as md
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", default="", help="comma-separated model ids (default: every id the settings use)")
    ap.add_argument("--skip-thinking", action="store_true", help="build without the thinking request fields")
    args = ap.parse_args()

    ids = model_ids()
    if args.models:
        ids = {m.strip(): ids.get(m.strip(), AGENT_FOR_TIER) for m in args.models.split(",") if m.strip()}
    print(f"strands-agents {md.version('strands-agents')} · {len(ids)} model id(s)\n")
    failed = False
    for mid, agent_name in ids.items():
        row = check_model(mid, agent_name, thinking=not args.skip_thinking)
        failed |= any(v.startswith("FAIL") for v in row.values())
        print(f"{mid}  (built as {agent_name})")
        for k, v in row.items():
            print(f"    {k:<9} {v}")
    skill = check_skill_activation()
    failed |= skill.startswith("FAIL")
    print(f"\nactivate_skill (web-research → web_search, web_fetch): {skill}")
    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
