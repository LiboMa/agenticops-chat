"""Which model each direct call runs on, and what reaches agent_logs (2026-11-07 model-config fixes).

Measured on the dev box 2026-11-06/07: the paths below read settings.bedrock_model_id, which /etc/agenticops.env pins
to Opus 4.6, while every agent ran a 5.5 model; Galaxy failed every build on Opus 5.5's 400 for `temperature`; and an
L1 fix plan ran on the executor's smart model (Sonnet 4.6) but was logged and priced as the executor's own model.

Owner decisions: the direct paths follow the MAIN agent's model; ACP's Claude Code follows Main too.
"""
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.config import settings

MAIN = "global.anthropic.claude-opus-5-5"
SMART = "global.anthropic.claude-sonnet-5-5"
HAIKU_45 = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
PINNED = "global.anthropic.claude-opus-4-6-v1"      # the env pin the direct paths must no longer read
REASONING = {"reasoningContent": {"reasoningText": {"text": "", "signature": "c2ln"}}}


def _reply(*texts, stop="end_turn"):
    """A Converse reply from a model that thinks by default: a reasoning block, then the text blocks."""
    return {
        "output": {"message": {"role": "assistant", "content": [REASONING, *({"text": t} for t in texts)]}},
        "stopReason": stop,
        "usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
    }


EMPTY_REPLY = {"output": {"message": {"role": "assistant", "content": [REASONING]}}, "stopReason": "end_turn"}


@pytest.fixture
def main_model(monkeypatch):
    monkeypatch.setattr(settings, "agent_main_model_id", MAIN)
    monkeypatch.setattr(settings, "agent_main_max_tokens", 12000)
    monkeypatch.setattr(settings, "bedrock_model_id", PINNED)


@pytest.fixture
def runtime():
    """The bedrock-runtime client behind every direct call; records client() and converse()."""
    client = MagicMock()
    session = MagicMock()
    session.client.return_value = client
    with patch("agenticops.config.get_bedrock_boto_session", return_value=session):
        yield session, client


def _client_config(session):
    config = session.client.call_args.kwargs["config"]
    return config.read_timeout, config.retries


# ── the four direct paths follow Main ────────────────────────────────────────

class TestDirectPathsFollowMain:
    def test_skill_generation(self, main_model, runtime):
        session, client = runtime
        client.converse.return_value = _reply(json.dumps(
            {"name": "redis-admin", "description": "Redis operations", "content": "## Redis\nsteps"}))
        from agenticops.skills.evolution import generate_skill_from_description
        assert generate_skill_from_description("a redis skill")["name"] == "redis-admin"
        assert client.converse.call_args.kwargs["modelId"] == MAIN
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 12000}
        assert _client_config(session) == (300, {"total_max_attempts": 2})

    def test_skill_improvement_writes_no_draft_from_an_empty_reply(self, main_model, runtime, tmp_path):
        _, client = runtime
        client.converse.return_value = EMPTY_REPLY
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text('---\nname: my-skill\ndescription: "x"\n---\n\n## Body', encoding="utf-8")
        drafts = tmp_path / "drafts"
        from agenticops.skills.evolution import auto_improve_skill
        with patch("agenticops.skills.evolution.settings") as evolution_settings, \
             patch("agenticops.skills.loader.discover_skills",
                   return_value=[SimpleNamespace(name="my-skill", path=skill_dir, description="x")]):
            evolution_settings.skills_draft_dir = drafts
            result = auto_improve_skill("my-skill", "needs examples")
        assert "error" in result
        assert not drafts.exists()
        assert client.converse.call_args.kwargs["modelId"] == MAIN

    def test_case_distillation(self, main_model, runtime):
        session, client = runtime
        client.converse.return_value = _reply(json.dumps({"title": "Leak", "tags": ["cpu"]}))
        from agenticops.tools.kb_tools import _llm_distill
        assert _llm_distill({"issue_id": 1}) == {"title": "Leak", "tags": ["cpu"]}
        assert client.converse.call_args.kwargs["modelId"] == MAIN
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 12000}
        assert _client_config(session) == (300, {"total_max_attempts": 2})

    def test_case_distillation_is_none_on_an_empty_reply(self, main_model, runtime):
        _, client = runtime
        client.converse.return_value = EMPTY_REPLY
        from agenticops.tools.kb_tools import _llm_distill
        assert _llm_distill({"issue_id": 1}) is None

    def test_sop_generation(self, main_model, runtime):
        _, client = runtime
        client.converse.return_value = _reply("---\nresource_type: EC2\n---\n# SOP")
        from agenticops.pipeline.sop_upgrader import _call_llm
        assert _call_llm("prompt") == "---\nresource_type: EC2\n---\n# SOP"
        assert client.converse.call_args.kwargs["modelId"] == MAIN
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 12000}

    def test_sop_upgrade_keeps_the_original_on_an_empty_reply(self, main_model, runtime):
        _, client = runtime
        client.converse.return_value = EMPTY_REPLY
        from agenticops.pipeline.sop_upgrader import upgrade_existing_sop
        original = "---\nresource_type: EC2\n---\n# Old SOP\n1. restart"
        assert upgrade_existing_sop(original, {"resource_type": "EC2", "root_cause": "leak"}) == original

    def test_legacy_rca_engine(self, main_model, runtime):
        _, client = runtime
        client.converse.return_value = _reply('{"root_cause": "leak"}')
        from agenticops.analyze.rca import BedrockLLM
        llm = BedrockLLM()
        assert llm.model_id == MAIN          # _save_rca_result stores this as RCAResult.model_id
        assert llm.invoke("prompt") == '{"root_cause": "leak"}'
        assert client.converse.call_args.kwargs["modelId"] == MAIN


# ── the existing converse helpers: temperature where the model takes it ──────

class TestTemperatureFollowsTheModel:
    @pytest.mark.parametrize("model,inference", [
        (MAIN, {"maxTokens": 300}),
        (HAIKU_45, {"maxTokens": 300, "temperature": 0}),
    ])
    def test_signal_gate_call(self, runtime, model, inference):
        """Also the RCA critic's and the security advisor's call."""
        _, client = runtime
        client.converse.return_value = _reply('{"merge": false}')
        from agenticops.services.signal_gate import _call_bedrock
        assert _call_bedrock("prompt", model, max_tokens=300) == ('{"merge": false}', {"input": 10, "output": 20})
        assert client.converse.call_args.kwargs["inferenceConfig"] == inference

    def test_galaxy_call(self, runtime):
        session, client = runtime
        client.converse.return_value = _reply('{"edges": []}')
        from agenticops.galaxy.builder import _call_bedrock
        assert _call_bedrock("prompt", MAIN, 16384) == ('{"edges": []}', {"input": 10, "output": 20})
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 16384}
        assert _client_config(session) == (300, {"total_max_attempts": 2})

    def test_translation_call(self, runtime):
        session, client = runtime
        client.converse.return_value = _reply("译文")
        from agenticops.services.content_rendering import _call_model
        assert _call_model("prompt", HAIKU_45, 4000) == "译文"
        assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 4000, "temperature": 0}
        assert _client_config(session) == (300, {"total_max_attempts": 2})   # "at most one retry"

    def test_translation_cut_at_the_limit_is_too_long(self, runtime):
        _, client = runtime
        client.converse.return_value = _reply("half a transl", stop="max_tokens")
        from agenticops.services.content_rendering import TranslationTruncated, _call_model
        with pytest.raises(TranslationTruncated):
            _call_model("prompt", HAIKU_45, 4000)


# ── agent_logs records the model that ran ────────────────────────────────────

class TestAgentLogsRecordTheModelThatRan:
    def test_an_explicit_model_is_recorded(self, monkeypatch):
        from agenticops.services import agent_log_service as svc
        logged = {}
        monkeypatch.setattr(svc, "log_agent_call", lambda **kw: logged.update(kw))
        monkeypatch.setattr(settings, "agent_executor_model_id", MAIN)
        with svc.track_agent("executor", "execute_fix", "fix_plan_id=1", model_id=SMART):
            pass
        assert logged["model_id"] == SMART

    def test_without_one_the_configured_model_is_recorded(self, monkeypatch):
        from agenticops.services import agent_log_service as svc
        logged = {}
        monkeypatch.setattr(svc, "log_agent_call", lambda **kw: logged.update(kw))
        monkeypatch.setattr(settings, "agent_executor_model_id", MAIN)
        with svc.track_agent("executor", "execute_fix", "fix_plan_id=1"):
            pass
        assert logged["model_id"] == MAIN

    def test_the_row_is_priced_at_the_model_that_ran(self):
        from agenticops.services import agent_log_service as svc
        rows = []

        class FakeDB:
            def add(self, obj):
                rows.append(obj)

        @contextmanager
        def fake_session():
            yield FakeDB()

        with patch("agenticops.models.get_db_session", fake_session):
            svc.log_agent_call(agent_name="executor", action="execute_fix", input_summary="x",
                               input_tokens=1_000_000, output_tokens=1_000_000, model_id=SMART)
        assert rows[0].model_id == SMART
        assert rows[0].cost_usd == pytest.approx(12.0)   # Sonnet 5.5 on Bedrock: $2 in + $10 out per 1M


# ── the executor builds and logs its smart model for L0/L1 ───────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.models import Base, get_session
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/routing.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


def _approved_fix_plan(db, risk_level):
    from agenticops.models import FixPlan, HealthIssue, RCAResult
    from agenticops.services.plan_content import stamp_approval
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned",
                        resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk_level, title="p", summary="s",
                   status="approved")
    db.add(plan); db.flush()
    stamp_approval(db, plan)
    db.commit()
    return plan.id


@contextmanager
def _executor_run():
    """executor_agent without Bedrock; yields the BedrockModel and track_agent mocks."""
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent"), patch(f"{ea}.BedrockModel") as model_cls, \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="done"), \
         patch("agenticops.services.agent_log_service.track_agent") as track:
        yield model_cls, track


@pytest.mark.parametrize("risk_level,expected", [("L1", SMART), ("L2", MAIN)])
def test_the_executor_logs_the_model_it_built(db, monkeypatch, risk_level, expected):
    monkeypatch.setattr(settings, "agent_executor_model_id", MAIN)
    monkeypatch.setattr(settings, "executor_smart_model", True)
    monkeypatch.setattr(settings, "executor_simple_model_id", SMART)
    pid = _approved_fix_plan(db, risk_level)
    from agenticops.agents.executor_agent import executor_agent
    with _executor_run() as (model_cls, track):
        assert executor_agent(fix_plan_id=pid) == "done"
    assert model_cls.call_args.kwargs["model_id"] == expected
    assert track.call_args.kwargs["model_id"] == expected


# ── ACP's Claude Code follows Main on Bedrock ────────────────────────────────

@pytest.mark.parametrize("main,on_bedrock,expected", [
    (MAIN, True, MAIN),
    ("global.openai.gpt-6-astra", True, None),   # Claude Code cannot run a non-Claude model: its own default
    (MAIN, False, None),                          # a global.anthropic.* id is not an Anthropic API model name
    ("global.openai.gpt-6-astra", False, None),
])
def test_acp_claude_code_runs_mains_model(monkeypatch, main, on_bedrock, expected):
    monkeypatch.setattr(settings, "agent_main_model_id", main)
    monkeypatch.setattr(settings, "acp_use_bedrock", on_bedrock)
    from agenticops.acp.backends.claude_code import ClaudeCodeBackend
    assert ClaudeCodeBackend()._client._env.get("ANTHROPIC_MODEL") == expected
