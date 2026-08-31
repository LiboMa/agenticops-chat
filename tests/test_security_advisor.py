"""Stage 5: evidence-grounded LLM advisor (fail-closed)."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops import models
from agenticops.security.advisor import _build_prompt, _grounded, _parse_recommendations
from agenticops.security.collectors import PostureFinding
from agenticops.security.scoring import score


@pytest.fixture
def sess_factory():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def _sess():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return _sess


def _findings():
    return [PostureFinding("network", "cis-4.1", "sg-1", "SecurityGroup", "0.0.0.0/0:22", "high")]


_LLM_OK = ('[{"category": "network", "title": "Restrict SSH", "detail": "close it", '
           '"evidence_refs": ["sg-1"], "severity": "high", "confidence": 0.9}]')


class TestParseRecommendations:
    def test_parses_fenced_json_array(self):
        text = "```json\n[{\"category\": \"iam\", \"title\": \"t\"}]\n```"
        assert _parse_recommendations(text) == [{"category": "iam", "title": "t"}]

    def test_garbage_returns_empty(self):
        assert _parse_recommendations("no json here") == []

    def test_json_object_not_array_returns_empty(self):
        assert _parse_recommendations('{"category": "iam"}') == []


class TestGrounding:
    def test_unknown_ref_dropped(self):
        recs = [{"title": "t", "evidence_refs": ["sg-1", "sg-GHOST"]}]
        assert _grounded(recs, {"sg-1"}) == []

    def test_empty_refs_dropped(self):
        assert _grounded([{"title": "t", "evidence_refs": []}], {"sg-1"}) == []

    def test_fully_grounded_kept(self):
        recs = [{"title": "t", "evidence_refs": ["sg-1"]}]
        assert _grounded(recs, {"sg-1", "vol-2"}) == recs


class TestPrompt:
    def test_prompt_contains_low_categories_and_evidence(self):
        f = PostureFinding("network", "cis-4.1", "sg-1", "SecurityGroup", "0.0.0.0/0:22", "high")
        p = _build_prompt("acct-a", {"network": 50.0, "iam": 100.0}, [f])
        assert "network" in p
        assert "sg-1" in p and "cis-4.1" in p
        assert "iam" not in p.split("Evidence")[0]  # 100-scoring category not listed as low


class TestRecommend:
    def _run(self, sess_factory, llm_side_effect, critic_enabled=True):
        import agenticops.security.advisor as adv
        with patch("agenticops.security.advisor.get_db_session", sess_factory), \
             patch("agenticops.services.signal_gate._call_bedrock",
                   side_effect=llm_side_effect), \
             patch("agenticops.config.settings.security_advisor_critic_enabled",
                   critic_enabled):
            return adv.recommend(None, "acct-a", score(_findings()), _findings())

    def test_grounded_supported_recommendation_persisted(self, sess_factory):
        calls = [(_LLM_OK, {}), ('{"verdict": "supported", "notes": ""}', {})]
        n = self._run(sess_factory, calls)
        assert n == 1
        with sess_factory() as s:
            rec = s.query(models.SecurityRecommendation).one()
            assert rec.title == "Restrict SSH"
            assert rec.critic_verdict == "supported"
            assert rec.evidence_refs == ["sg-1"]
            assert rec.status == "open"

    def test_critic_refuted_dropped(self, sess_factory):
        calls = [(_LLM_OK, {}), ('{"verdict": "refuted", "notes": "wrong"}', {})]
        n = self._run(sess_factory, calls)
        assert n == 0
        with sess_factory() as s:
            assert s.query(models.SecurityRecommendation).count() == 0

    def test_ungrounded_ref_dropped_before_critic(self, sess_factory):
        bad = _LLM_OK.replace("sg-1", "sg-GHOST")
        n = self._run(sess_factory, [(bad, {})])
        assert n == 0

    def test_llm_exception_fail_closed(self, sess_factory):
        n = self._run(sess_factory, RuntimeError("bedrock down"))
        assert n == 0

    def test_critic_disabled_defaults_supported(self, sess_factory):
        n = self._run(sess_factory, [(_LLM_OK, {})], critic_enabled=False)
        assert n == 1
        with sess_factory() as s:
            assert s.query(models.SecurityRecommendation).one().critic_verdict == "supported"
