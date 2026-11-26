"""Single-turn calls on a non-Bedrock provider (MVP-2.9.0 N35) — what `preamble.converse_text` hands a
`<provider>::<model>` reference to. The same contract: (text, {"input", "output"}, stop reason); reasoning content
skipped; a reply with no text raises ModelReplyEmpty, one cut at max_tokens ModelReplyTruncated; `temperature` only
where the model takes it; read timeout and total attempts per call. An SDK error (timeout, rate limit, auth) is
raised as it is — chat/stream_errors words it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Reply:
    text: str
    usage: dict
    stop: str
    tool_called: bool
    truncated: bool


def send(cfg, model_id: str, prompt: str, *, max_tokens: int, tool: Optional[tuple[str, str]] = None,
         temperature: Optional[float] = None, timeout: Optional[float] = None, max_retries: int = 0) -> Reply:
    """ONE user message to `model_id` of the provider `cfg` — the only place a chat request to another provider is
    built (review of MVP-2.9.0: the connection test had its own). `tool` = (name, description) of one tool without
    parameters the model may call (the connection test's tool step). Reasoning content is skipped; the caller decides
    what an empty or a cut reply means."""
    from agenticops.llm.factory import client_args
    args = client_args(cfg, timeout=timeout, max_retries=max_retries)
    sampling = {"temperature": temperature} if temperature is not None else {}
    messages = [{"role": "user", "content": prompt}]
    if cfg.kind == "anthropic_compatible":
        import anthropic
        kwargs: dict = {"model": model_id, "max_tokens": max_tokens, "messages": messages, **sampling}
        if tool:
            kwargs["tools"] = [{"name": tool[0], "description": tool[1], "input_schema": {"type": "object", "properties": {}}}]
        resp = anthropic.Anthropic(**args).messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        stop = resp.stop_reason or ""
        usage = {"input": int(resp.usage.input_tokens or 0), "output": int(resp.usage.output_tokens or 0)}
        return Reply(text, usage, stop, any(getattr(b, "type", "") == "tool_use" for b in resp.content), stop == "max_tokens")
    import openai
    kwargs = {"model": model_id, "max_tokens": max_tokens, "messages": messages, **sampling}
    if tool:
        kwargs["tools"] = [{"type": "function", "function": {
            "name": tool[0], "description": tool[1], "parameters": {"type": "object", "properties": {}}}}]
        kwargs["tool_choice"] = "auto"
    resp = openai.OpenAI(**args).chat.completions.create(**kwargs)
    choice = resp.choices[0] if resp.choices else None
    u = resp.usage
    usage = {"input": int(getattr(u, "prompt_tokens", 0) or 0), "output": int(getattr(u, "completion_tokens", 0) or 0)}
    if choice is None:
        return Reply("", usage, "", False, False)
    stop = choice.finish_reason or ""
    return Reply(choice.message.content or "", usage, stop, bool(choice.message.tool_calls), stop == "length")


def complete_text(ref: str, prompt: str, *, max_tokens: int, temperature: Optional[float] = None,
                  read_timeout: Optional[int] = None, total_attempts: Optional[int] = None) -> tuple[str, dict, str]:
    from agenticops.agents.preamble import ModelReplyEmpty, ModelReplyTruncated, accepts_temperature
    from agenticops.llm.factory import resolve
    from agenticops.llm.refs import parse_ref
    cfg, _row = resolve(ref)
    reply = send(cfg, parse_ref(ref).model_id, prompt, max_tokens=max_tokens,
                 temperature=temperature if temperature is not None and accepts_temperature(ref) else None,
                 timeout=read_timeout, max_retries=max(0, (total_attempts or 3) - 1))
    if reply.truncated:
        raise ModelReplyTruncated(f"{ref} stopped at its {max_tokens}-token output limit")
    if not reply.text.strip():
        raise ModelReplyEmpty(f"{ref} returned no text")
    return reply.text, reply.usage, reply.stop
