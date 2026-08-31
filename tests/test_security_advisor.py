"""Stage 5: evidence-grounded LLM advisor (fail-closed)."""
from unittest.mock import MagicMock, patch

from agenticops.security.advisor import _build_prompt, _grounded, _parse_recommendations
from agenticops.security.collectors import PostureFinding


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
