"""A provider model's thinking request shape is its row's «reasoning» (review of MVP-2.9.0, 2026-11-26).

Until now one value, `anthropic_thinking`, left the shape to the Claude version in the model id: adaptive from 4.6,
a token budget before, and `display: summarized` from 4.7. The row now says which: `anthropic_adaptive_summarized`,
`anthropic_adaptive` or `anthropic_budget` (the owner kept the summary as a value of its own). A startup migration
gives every old row the shape it was sent until now — the last time a provider model's name is read."""
import pytest

from tests.llm_fake_server import add_model, add_provider, llm_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    return llm_db(tmp_path, monkeypatch, "reasoning-values.db")


@pytest.mark.parametrize("model_id,value", [
    ("claude-opus-5-5", "anthropic_adaptive_summarized"),
    ("global.anthropic.claude-sonnet-5-5", "anthropic_adaptive_summarized"),
    ("claude-opus-4-7", "anthropic_adaptive_summarized"),
    ("claude-sonnet-4-6", "anthropic_adaptive"),
    ("claude-haiku-4-5-20251001", "anthropic_budget"),
    ("claude-3-5-haiku-20241022", "anthropic_budget"),
    ("plain-alias", "anthropic_budget"),
])
def test_the_shape_a_claude_id_takes(model_id, value):
    from agenticops.agents.preamble import claude_reasoning
    assert claude_reasoning(model_id) == value


def _reasoning() -> dict:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return {r.model_id: r.reasoning for r in s.query(ProviderModel).all()}


def test_old_rows_get_the_shape_they_were_sent(db):
    from agenticops import models
    add_provider("relay", "https://relay.example.com/", kind="anthropic_compatible", api_key="k")
    for mid in ("claude-opus-5-5", "claude-sonnet-4-6", "claude-3-5-haiku-20241022", "plain-alias"):
        add_model("relay", mid, reasoning="anthropic_thinking")
    add_model("relay", "o-think", reasoning="openai_effort")
    add_model("relay", "quiet", reasoning="none")
    models._migrate_reasoning_values_2_9_0(models.get_engine())
    after = _reasoning()
    assert after == {"claude-opus-5-5": "anthropic_adaptive_summarized", "claude-sonnet-4-6": "anthropic_adaptive",
                     "claude-3-5-haiku-20241022": "anthropic_budget", "plain-alias": "anthropic_budget",
                     "o-think": "openai_effort", "quiet": "none"}
    models._migrate_reasoning_values_2_9_0(models.get_engine())           # a second run changes nothing
    assert _reasoning() == after


def test_a_migrated_row_sends_what_it_sent_before(db):
    """The request after the migration is the request before it, for each old shape."""
    from agenticops import models
    from agenticops.agents.preamble import thinking_fields_for_budget
    from agenticops.llm.factory import build_model
    add_provider("relay", "https://relay.example.com/", kind="anthropic_compatible", api_key="k")
    ids = ("claude-opus-5-5", "claude-sonnet-4-6", "claude-3-5-haiku-20241022")
    for mid in ids:
        add_model("relay", mid, reasoning="anthropic_thinking")
    before = {mid: thinking_fields_for_budget(8192, 16000, mid) for mid in ids}     # what the old factory sent
    models._migrate_reasoning_values_2_9_0(models.get_engine())
    for mid in ids:
        assert build_model(f"relay::{mid}", max_tokens=16000, thinking_budget=8192).config["params"] == before[mid]


def test_init_db_runs_it(db, monkeypatch):
    from agenticops import models
    add_provider("relay", "https://relay.example.com/", kind="anthropic_compatible", api_key="k")
    add_model("relay", "claude-sonnet-4-6", reasoning="anthropic_thinking")
    monkeypatch.setattr(models, "_migrated_urls", set())          # this process migrated it already
    models.init_db()
    assert _reasoning() == {"claude-sonnet-4-6": "anthropic_adaptive"}
