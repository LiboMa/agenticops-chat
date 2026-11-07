"""The single-shot Bedrock Converse helper (agents/preamble.converse_text) and its temperature gate.

Every direct (non-Strands) model call goes through converse_text, so these are the request and reply rules for all
of them:
- Claude 4.7+ rejects sampling parameters on Bedrock — Opus 5.5 answered 400 "`temperature` is deprecated for this
  model" on every Galaxy build from 2026-11-06 07:00 (measured on the dev box); Sonnet 5.5 / Haiku 5.5 reject
  non-default values. Older Claude models still take temperature 0.
- 5.x models think by default, so a reply may open with a reasoningContent block before its text.
- An empty or cut-off reply must fail loudly: the old `content[0]["text"]` raised on a reasoning block, and an empty
  string passed on as an answer would complete a Galaxy build with no edges or overwrite an SOP with nothing.
"""
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from agenticops.agents.preamble import (
    ModelReplyEmpty,
    ModelReplyError,
    ModelReplyTruncated,
    accepts_temperature,
    converse_inference_config,
    converse_text,
)

OPUS_55 = "global.anthropic.claude-opus-5-5"
HAIKU_45 = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
REASONING = {"reasoningContent": {"reasoningText": {"text": "", "signature": "c2ln"}}}


def _reply(content, stop="end_turn", usage=None):
    """A Bedrock Converse response in its documented shape."""
    return {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": usage or {"inputTokens": 12, "outputTokens": 34, "totalTokens": 46},
        "metrics": {"latencyMs": 120},
    }


@pytest.fixture
def runtime():
    """The bedrock-runtime client converse_text gets from the Bedrock session; records client() and converse()."""
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    with patch("agenticops.config.get_bedrock_boto_session", return_value=session):
        yield session, client


class TestTemperatureGate:
    @pytest.mark.parametrize("mid", [
        "global.anthropic.claude-opus-5-5",
        "global.anthropic.claude-sonnet-5-5",
        "global.anthropic.claude-haiku-5-5",
        "global.anthropic.claude-opus-5",
        "global.anthropic.claude-sonnet-5",
        "global.anthropic.claude-fable-5-1",
        "global.anthropic.claude-opus-4-8",
        "global.anthropic.claude-opus-4-7",
        "global.openai.gpt-6-astra",       # not Claude: omitting is always valid
        "openai.gpt-oss-120b-1:0",
        "",
    ])
    def test_models_that_reject_it_or_are_not_claude_get_none(self, mid):
        assert accepts_temperature(mid) is False

    @pytest.mark.parametrize("mid", [
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        "global.anthropic.claude-sonnet-4-6",
        "global.anthropic.claude-opus-4-6-v1",
        "us.anthropic.claude-sonnet-4-20250514-v1:0",   # a dated 4.0 id is 4.0, not 4.20250514
        "anthropic.claude-v2",                          # no claude-<family>-<n> shape: pre-4 Claude
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
    ])
    def test_claude_before_4_7_keeps_it(self, mid):
        assert accepts_temperature(mid) is True

    def test_inference_config_drops_temperature_only_where_rejected(self):
        assert converse_inference_config(OPUS_55, 500, temperature=0) == {"maxTokens": 500}
        assert converse_inference_config(HAIKU_45, 500, temperature=0) == {"maxTokens": 500, "temperature": 0}
        assert converse_inference_config(HAIKU_45, 500) == {"maxTokens": 500}


class TestConverseText:
    def test_a_leading_reasoning_block_is_skipped(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([REASONING, {"text": "the answer"}])
        assert converse_text(OPUS_55, "q", max_tokens=100) == ("the answer", {"input": 12, "output": 34}, "end_turn")

    def test_text_blocks_are_joined_in_order(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([{"text": "first "}, REASONING, {"text": "second"}])
        assert converse_text(OPUS_55, "q", max_tokens=100)[0] == "first second"

    def test_a_reply_with_no_text_raises(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([REASONING])
        with pytest.raises(ModelReplyEmpty):
            converse_text(OPUS_55, "q", max_tokens=100)

    def test_a_reply_cut_at_the_output_limit_raises(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([{"text": "half a JSON obj"}], stop="max_tokens")
        with pytest.raises(ModelReplyTruncated):
            converse_text(OPUS_55, "q", max_tokens=100)

    def test_both_failures_share_one_base_class(self, runtime):
        _, client = runtime
        for reply in (_reply([REASONING]), _reply([{"text": "x"}], stop="max_tokens")):
            client.converse.return_value = reply
            with pytest.raises(ModelReplyError):
                converse_text(OPUS_55, "q", max_tokens=100)

    def test_a_reply_without_usage_or_stop_reason_still_parses(self, runtime):
        _, client = runtime
        client.converse.return_value = {"output": {"message": {"content": [{"text": "ok"}]}}}
        assert converse_text(OPUS_55, "q", max_tokens=10) == ("ok", {"input": 0, "output": 0}, "")

    def test_the_request_omits_temperature_for_a_model_that_rejects_it(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([{"text": "ok"}])
        converse_text(OPUS_55, "the prompt", max_tokens=777, temperature=0)
        assert client.converse.call_args.kwargs == {
            "modelId": OPUS_55,
            "messages": [{"role": "user", "content": [{"text": "the prompt"}]}],
            "inferenceConfig": {"maxTokens": 777},
        }

    def test_the_request_keeps_temperature_for_a_model_that_takes_it(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply([{"text": "ok"}])
        converse_text(HAIKU_45, "p", max_tokens=5, temperature=0)
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 5, "temperature": 0}

    def test_read_timeout_and_total_attempts_reach_the_client(self, runtime):
        session, client = runtime
        client.converse.return_value = _reply([{"text": "ok"}])
        converse_text(OPUS_55, "q", max_tokens=10, read_timeout=300, total_attempts=2)
        assert session.client.call_args.args == ("bedrock-runtime",)
        config = session.client.call_args.kwargs["config"]
        assert config.read_timeout == 300
        assert config.retries == {"total_max_attempts": 2}   # total incl. the first try, not max_attempts (= retries)

    def test_no_client_config_when_neither_is_asked_for(self, runtime):
        session, client = runtime
        client.converse.return_value = _reply([{"text": "ok"}])
        converse_text(OPUS_55, "q", max_tokens=10)
        assert "config" not in session.client.call_args.kwargs


@pytest.mark.parametrize("module", ["agenticops.services.signal_gate", "agenticops.galaxy.builder"])
def test_a_caller_imports_cleanly_in_a_fresh_interpreter(module):
    """converse_text lives in agents.preamble, whose package __init__ imports every agent; that chain reaches back to
    signal_gate (via metadata_tools) and galaxy.builder (via graph.query_service). A top-level import of the helper
    in either module would be a circular import, so callers import it inside the function."""
    done = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-3000:]
