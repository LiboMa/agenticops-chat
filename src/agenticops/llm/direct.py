"""Single-turn calls on a non-Bedrock provider (MVP-2.9.0 N35) — what `preamble.converse_text` hands a
`<provider>::<model>` reference to. The same contract: (text, {"input", "output"}, stop reason); reasoning content
skipped; a reply with no text raises ModelReplyEmpty, one cut at max_tokens ModelReplyTruncated; `temperature` only
where the model takes it; read timeout and total attempts per call. An SDK error (timeout, rate limit, auth) is
raised as it is — chat/stream_errors words it."""
from __future__ import annotations

from typing import Optional


def complete_text(ref: str, prompt: str, *, max_tokens: int, temperature: Optional[float] = None,
                  read_timeout: Optional[int] = None, total_attempts: Optional[int] = None) -> tuple[str, dict, str]:
    from agenticops.agents.preamble import ModelReplyEmpty, ModelReplyTruncated, accepts_temperature
    from agenticops.llm.factory import client_args, resolve
    from agenticops.llm.refs import parse_ref
    cfg, _row = resolve(ref)
    model_id = parse_ref(ref).model_id
    args = client_args(cfg, timeout=read_timeout, max_retries=max(0, (total_attempts or 3) - 1))
    sampling = {"temperature": temperature} if temperature is not None and accepts_temperature(ref) else {}
    if cfg.kind == "anthropic_compatible":
        import anthropic
        resp = anthropic.Anthropic(**args).messages.create(
            model=model_id, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], **sampling)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        stop = resp.stop_reason or ""
        usage = {"input": int(resp.usage.input_tokens or 0), "output": int(resp.usage.output_tokens or 0)}
        truncated = stop == "max_tokens"
    else:
        import openai
        resp = openai.OpenAI(**args).chat.completions.create(
            model=model_id, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], **sampling)
        choice = resp.choices[0]
        text = choice.message.content or ""
        stop = choice.finish_reason or ""
        u = resp.usage
        usage = {"input": int(getattr(u, "prompt_tokens", 0) or 0), "output": int(getattr(u, "completion_tokens", 0) or 0)}
        truncated = stop == "length"
    if truncated:
        raise ModelReplyTruncated(f"{ref} stopped at its {max_tokens}-token output limit")
    if not text.strip():
        raise ModelReplyEmpty(f"{ref} returned no text")
    return text, usage, stop
