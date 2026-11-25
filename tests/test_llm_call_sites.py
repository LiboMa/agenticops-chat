"""Every model call goes through the one entry point (MVP-2.9.0 N35 task 5).

The agents build their model with `llm.factory.build_model` — a Bedrock id exactly as before, `<provider>::<model>`
with Strands' OpenAI / Anthropic models — and what reads a built model's id (attachments, the history budget) reads
the reference it was built from. Cost, the conversation window, the chat's error words, session titles, summaries and
the health check know a provider reference too; none of them reaches Bedrock for one.
"""
import ast
import json
import pathlib
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.llm_fake_server import FakeLLMServer, add_model, add_provider, llm_db

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_CLASSES = ("BedrockModel", "OpenAIModel", "AnthropicModel")


@pytest.fixture
def db(tmp_path, monkeypatch):
    return llm_db(tmp_path, monkeypatch, "n35-sites.db")


# ── one place builds a model ─────────────────────────────────────────────────

def model_class_calls(src: pathlib.Path) -> list[str]:
    """Every call of a Strands model class (by name, or the factory's `bedrock_cls`) under `src`, as `file:line`."""
    out = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name in MODEL_CLASSES or name == "bedrock_cls":
                    out.append(f"{path.relative_to(src)}:{node.lineno}")
    return out


def test_no_model_is_built_outside_the_factory():
    calls = model_class_calls(ROOT / "src" / "agenticops")
    assert calls and all(c.startswith("llm/factory.py:") for c in calls), calls


def test_the_scan_sees_the_old_build_sites(tmp_path):
    """The scan above is not blind: on the code before N35 it finds the nine build sites."""
    subprocess.run(f"git -C {ROOT} archive 78ab622 src/agenticops | tar -x -C {tmp_path}", shell=True, check=True)
    calls = model_class_calls(tmp_path / "src" / "agenticops")
    assert len([c for c in calls if not c.startswith("llm/")]) == 9, calls


BUILDS = {"agents/main_agent.py": 1, "agents/scan_agent.py": 1, "agents/detect_agent.py": 2,
          "agents/rca_agent.py": 1, "agents/sre_agent.py": 1, "agents/executor_agent.py": 1,
          "agents/reporter_agent.py": 1, "cli/context.py": 1}


def test_every_build_site_calls_build_model():
    for rel, n in BUILDS.items():
        tree = ast.parse((ROOT / "src" / "agenticops" / rel).read_text(encoding="utf-8"))
        calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id == "build_model"]
        assert len(calls) == n, rel


@pytest.fixture
def provider(db, monkeypatch):
    from agenticops.config import settings
    add_provider("local-llm", "http://127.0.0.1:9/v1", api_key="k")
    add_model("local-llm", "qwen3:32b", reasoning="openai_effort", supports_tools=True)
    for agent in ("main", "sre", "detect"):
        monkeypatch.setattr(settings, f"agent_{agent}_model_id", "local-llm::qwen3:32b")
    monkeypatch.setattr(settings, "skills_enabled", False)
    monkeypatch.setattr(settings, "mcp_servers_config", "")
    return settings


def test_agents_run_on_a_provider_model(provider):
    """Main, the SRE agent and a detection worker built as the product builds them, on a provider's model: an
    OpenAIModel that carries the reference, and not one Bedrock session asked for."""
    from strands.models.openai import OpenAIModel
    from agenticops.agents.detect_agent import _build_detect_agent_for_account
    from agenticops.agents.main_agent import create_main_agent
    from agenticops.agents.sre_agent import _create_sre_agent
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        agents = [create_main_agent(), _create_sre_agent(fix_plan=True),
                  _build_detect_agent_for_account("prod", 1, MagicMock(__name__="run_aws_cli_readonly"), None)]
    for agent in agents:
        assert isinstance(agent.model, OpenAIModel) and agent.model.aiops_ref == "local-llm::qwen3:32b"
        assert "cache_config" not in agent.model.config


def test_main_and_rca_pass_their_thinking_budget(provider, monkeypatch):
    from tests.test_run_guard import Scripted
    seen = {}

    def recorder(ref, *, max_tokens, thinking_budget=0, bedrock_cls=None):
        seen.setdefault("calls", []).append((ref, max_tokens, thinking_budget))
        return Scripted([])
    monkeypatch.setattr("agenticops.llm.factory.build_model", recorder)
    monkeypatch.setattr(provider, "agent_main_max_tokens", 16384)
    from agenticops.agents.main_agent import create_main_agent
    create_main_agent(effort_override="high")
    assert seen["calls"][-1] == ("local-llm::qwen3:32b", 16384, 8192)

    ra = "agenticops.agents.rca_agent"
    with patch("agenticops.config.get_agent_model_config", return_value=("local-llm::qwen3:32b", 16384)), \
            patch(f"{ra}.build_system_prompt", return_value="p"), \
            patch(f"{ra}.resolve_rca_effort", return_value=(12288, "critical severity")), \
            patch("agenticops.agents.preamble.invoke_with_retry", return_value="done"), \
            patch("agenticops.services.agent_log_service.track_agent"), \
            patch("agenticops.services.rca_quality.run_post_rca_pipeline"):
        from agenticops.agents.rca_agent import rca_agent
        assert rca_agent(issue_id=7) == "done"
    assert seen["calls"][-1] == ("local-llm::qwen3:32b", 16384, 12288)


# ── what reads a built model's id reads its reference ────────────────────────

def test_attachments_read_the_ref(db):
    """OpenRouter's «anthropic/claude-sonnet-4.5», listed as reading no documents: a PDF goes as text, though the raw
    id has «claude» in it (a Bedrock Claude id would read it natively)."""
    from agenticops.chat.attachments.budget_hook import AttachmentBudgetHook
    from agenticops.chat.attachments.delivery import agent_model_id
    from agenticops.llm.factory import build_model
    add_provider("openrouter", "https://openrouter.ai/api/v1", api_key="k")
    add_model("openrouter", "anthropic/claude-sonnet-4.5", supports_images=True, supports_documents=False)
    agent = SimpleNamespace(model=build_model("openrouter::anthropic/claude-sonnet-4.5", max_tokens=100))
    assert agent_model_id(agent) == "openrouter::anthropic/claude-sonnet-4.5"
    seen = {}
    with patch("agenticops.chat.attachments.budget_hook.enforce_history_budget",
               side_effect=lambda messages, caps, cfg: seen.setdefault("caps", caps) and 0):
        AttachmentBudgetHook()._before_model_call(SimpleNamespace(agent=SimpleNamespace(model=agent.model, messages=[])))
    assert tuple(seen["caps"]) == (True, False)


# ── cost and window ──────────────────────────────────────────────────────────

def test_cost_of_a_ref(db, caplog):
    from agenticops.cost import compute_cost, compute_cost_breakdown
    add_provider("openrouter", "https://openrouter.ai/api/v1", api_key="k")
    add_model("openrouter", "priced", price_input=3.0, price_output=15.0, price_cache_read=0.3)
    add_model("openrouter", "free")
    tokens = {"input": 1_000_000, "output": 100_000, "cache_read": 1_000_000}
    assert compute_cost("openrouter::priced", tokens) == pytest.approx(3.0 + 1.5 + 0.3)
    assert compute_cost_breakdown("openrouter::priced", tokens)["cache_write"] == 0.0
    caplog.clear()
    assert compute_cost("openrouter::free", tokens) == 0.0
    assert compute_cost("nowhere::m", tokens) == 0.0
    assert not [r for r in caplog.records if r.levelname == "WARNING"]        # an unpriced model is not a fault
    assert compute_cost("global.anthropic.claude-opus-4-6-v1", {"input": 1_000_000}) > 0   # Bedrock unchanged


def test_window_of_a_ref(monkeypatch):
    """A provider's model takes the plain window, never a Bedrock family's — «claude-opus-5» on Bedrock keeps the RCA's
    whole context, which a provider's smaller model would overflow; the agent's own setting still wins."""
    from agenticops.config import FULL_CONTEXT, get_agent_window_size, settings
    monkeypatch.setattr(settings, "agent_rca_window_size", 0)
    monkeypatch.setattr(settings, "agent_rca_model_id", "global.anthropic.claude-opus-5-5")
    assert get_agent_window_size("rca") == FULL_CONTEXT
    monkeypatch.setattr(settings, "agent_rca_model_id", "openrouter::anthropic/claude-opus-5-5")
    assert get_agent_window_size("rca") == settings.bedrock_window_size
    from agenticops.config import validate_agent_model_ids
    monkeypatch.setattr(settings, "agent_rca_model_id", "ollama::llama3.1:8b")    # no Bedrock family in its name
    assert get_agent_window_size("rca") == settings.bedrock_window_size
    assert not [w for w in validate_agent_model_ids() if "agent_rca_model_id" in w]    # by design, not drift
    monkeypatch.setattr(settings, "agent_rca_window_size", 12)
    assert get_agent_window_size("rca") == 12


# ── the chat's error words ───────────────────────────────────────────────────

def _openai_error(cls_name, status, message="boom"):
    import httpx
    import openai
    req = httpx.Request("POST", "http://h/v1/chat/completions")
    if cls_name in ("APITimeoutError",):
        return openai.APITimeoutError(request=req)
    if cls_name == "APIConnectionError":
        return openai.APIConnectionError(request=req)
    resp = httpx.Response(status, request=req, json={"error": {"message": message}})
    return getattr(openai, cls_name)(message, response=resp, body={"error": {"message": message}})


def _anthropic_error(cls_name, status, message="boom"):
    import anthropic
    import httpx
    req = httpx.Request("POST", "http://h/v1/messages")
    if cls_name == "APITimeoutError":
        return anthropic.APITimeoutError(request=req)
    if cls_name == "APIConnectionError":
        return anthropic.APIConnectionError(request=req)
    resp = httpx.Response(status, request=req, json={"type": "error", "error": {"message": message}})
    return getattr(anthropic, cls_name)(message, response=resp, body={"error": {"message": message}})


@pytest.mark.parametrize("make", [_openai_error, _anthropic_error])
@pytest.mark.parametrize("cls_name,status,code", [
    ("RateLimitError", 429, "throttled"),
    ("APITimeoutError", 0, "timeout"),
    ("AuthenticationError", 401, "model_unavailable"),
    ("PermissionDeniedError", 403, "model_unavailable"),
    ("NotFoundError", 404, "model_unavailable"),
    ("APIConnectionError", 0, "model_unavailable"),
    ("InternalServerError", 500, "model_unavailable"),
    ("BadRequestError", 400, "request_rejected"),
])
def test_stream_errors_for_other_providers(make, cls_name, status, code):
    from agenticops.chat.stream_errors import classify
    assert classify(make(cls_name, status)) == code


def test_stream_error_details_for_other_providers():
    import httpx
    from agenticops.chat.stream_errors import classify, rejection_detail
    from agenticops.llm.factory import ModelProviderUnavailable
    overflow = _openai_error("BadRequestError", 400, "This model's maximum context length is 8192 tokens")
    assert classify(overflow) == "context_too_long"
    rejected = _anthropic_error("BadRequestError", 400, "tools.0: unknown field «eager»")
    assert rejection_detail(rejected) == "tools.0: unknown field «eager»"
    gone = ModelProviderUnavailable("local-llm::qwen3:32b", "provider_disabled", "the provider «local-llm» is turned off")
    assert classify(gone) == "model_unavailable"
    detail = rejection_detail(gone)
    assert "local-llm::qwen3:32b" in detail and "turned off" in detail
    assert classify(httpx.ReadTimeout("read timed out")) == "timeout"
    assert rejection_detail(_openai_error("AuthenticationError", 401, "Incorrect API key provided: sk-abc")) is None


# ── titles, summaries, the health check ──────────────────────────────────────

@pytest.fixture
def cheap_on_fake(db, monkeypatch):
    from agenticops.config import settings
    with FakeLLMServer() as fake:
        add_provider("cheap", f"{fake.base}/v1", api_key="k")
        add_model("cheap", "fake-chat-1")
        monkeypatch.setattr(settings, "bedrock_model_id_cheap", "cheap::fake-chat-1")
        fake.reply = "AWS health review"
        yield fake


def test_titles_and_summaries_use_converse_text(cheap_on_fake):
    from agenticops.web.app import _generate_session_title
    from agenticops.web.summary_service import SummaryService
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        assert _generate_session_title("check my aws health", "3 issues") == "AWS health review"
        with patch("agenticops.web.summary_service.get_db_session"):
            assert SummaryService().generate_summary([{"role": "user", "content": "hi", "_db_id": 1}], 1) == \
                "AWS health review"
    sent = [r["body"] for r in cheap_on_fake.requests if r["method"] == "POST"]
    assert [b["model"] for b in sent] == ["fake-chat-1", "fake-chat-1"]
    assert sent[0]["max_tokens"] == 30 and sent[1]["max_tokens"] == 500


def test_titles_and_summaries_on_bedrock_use_converse(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.web.app import _generate_session_title
    from agenticops.web.summary_service import SummaryService
    monkeypatch.setattr(settings, "bedrock_model_id_cheap", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
    with patch("agenticops.config.get_bedrock_boto_session") as session:
        client = session.return_value.client.return_value
        client.converse.return_value = {"output": {"message": {"content": [{"text": "Title"}]}},
                                        "stopReason": "end_turn", "usage": {"inputTokens": 1, "outputTokens": 1}}
        assert _generate_session_title("a", "b") == "Title"
        with patch("agenticops.web.summary_service.get_db_session"):
            assert SummaryService().generate_summary([{"role": "user", "content": "hi", "_db_id": 1}], 1) == "Title"
    assert not client.invoke_model.called and client.converse.call_count == 2


def test_health_skips_bedrock_when_it_is_off(db):
    from starlette.testclient import TestClient
    from agenticops.llm import registry
    from agenticops.web.app import app
    from tests.llm_fake_server import ADMIN
    registry.set_bedrock_enabled(False, ADMIN)
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        body = TestClient(app).get("/api/health").json()
    assert body["checks"]["aws"]["status"] == "skipped"
    assert body["status"] != "degraded" or body["checks"]["disk"]["status"] != "ok"
