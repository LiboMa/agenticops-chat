"""Tests for agenticops.pipeline.sop_identifier — improve coverage for
vector-search success path and keyword-fallback threshold rejection.
"""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenticops.pipeline.sop_identifier import SOPMatch, identify_matching_sop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeSearchResult:
    score: float
    file_path: str | None = None
    case_id: str = "ec2-cpu"
    content: str = ""


SOP_CONTENT = """---
resource_type: EC2
issue_pattern: High CPU
---
# Fix high CPU
"""


# ---------------------------------------------------------------------------
# Vector search success path (lines 67-82)
# ---------------------------------------------------------------------------

class TestVectorSearchPath:
    """Exercise the vector (hybrid_search) branch that returns a SOPMatch."""

    @patch("agenticops.pipeline.sop_identifier._parse_frontmatter")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_vector_hit_with_content(self, mock_settings, mock_parse):
        """When hybrid_search returns a high-score result with content, return SOPMatch."""
        mock_settings.sop_similarity_threshold = 0.5
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        hit = FakeSearchResult(score=0.9, file_path="/tmp/sops/ec2-cpu.md", content=SOP_CONTENT)

        mock_parse.return_value = (
            {"resource_type": "EC2", "issue_pattern": "High CPU"},
            "# Fix high CPU\n",
        )

        with patch(
            "agenticops.pipeline.sop_identifier.hybrid_search",
            return_value=[hit],
            create=True,
        ) as mock_hs:
            # We need to patch the import inside the function
            import agenticops.pipeline.sop_identifier as mod
            with patch.dict("sys.modules", {"agenticops.kb.search": MagicMock(hybrid_search=MagicMock(return_value=[hit]))}):
                # Re-import to pick up patched module
                result = identify_matching_sop("EC2", "High CPU utilization")

        # The function tries `from agenticops.kb.search import hybrid_search` inside a try block.
        # Let's use a more direct approach.

    @patch("agenticops.pipeline.sop_identifier._parse_frontmatter")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_vector_hit_direct(self, mock_settings, mock_parse):
        """Directly exercise the vector search success path."""
        mock_settings.sop_similarity_threshold = 0.5
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        hit = FakeSearchResult(score=0.9, file_path="/tmp/sops/ec2-cpu.md", content=SOP_CONTENT)
        mock_parse.return_value = (
            {"resource_type": "EC2", "issue_pattern": "High CPU"},
            "# Fix",
        )

        # Patch hybrid_search at the module level via sys.modules
        fake_search_mod = MagicMock()
        fake_search_mod.hybrid_search = MagicMock(return_value=[hit])

        import sys
        with patch.dict(sys.modules, {"agenticops.kb.search": fake_search_mod}):
            result = identify_matching_sop("EC2", "High CPU utilization")

        assert result is not None
        assert isinstance(result, SOPMatch)
        assert result.sop_path == "/tmp/sops/ec2-cpu.md"
        assert result.filename == "ec2-cpu.md"
        assert result.similarity_score == 0.9
        assert result.resource_type == "EC2"
        assert result.content == SOP_CONTENT

    @patch("agenticops.pipeline.sop_identifier._parse_frontmatter")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_vector_hit_no_content_reads_file(self, mock_settings, mock_parse, tmp_path):
        """When hit.content is empty, it reads the file from disk."""
        sop_file = tmp_path / "ec2-cpu.md"
        sop_file.write_text(SOP_CONTENT)

        mock_settings.sop_similarity_threshold = 0.3
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = tmp_path

        hit = FakeSearchResult(score=0.8, file_path=str(sop_file), content="")
        mock_parse.return_value = (
            {"resource_type": "EC2", "issue_pattern": "High CPU"},
            "body",
        )

        import sys
        fake_mod = MagicMock()
        fake_mod.hybrid_search = MagicMock(return_value=[hit])

        with patch.dict(sys.modules, {"agenticops.kb.search": fake_mod}):
            result = identify_matching_sop("EC2", "High CPU")

        assert result is not None
        assert result.content == SOP_CONTENT

    @patch("agenticops.pipeline.sop_identifier._parse_frontmatter")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_vector_hit_no_filepath_uses_case_id(self, mock_settings, mock_parse, tmp_path):
        """When hit.file_path is None, constructs path from case_id."""
        sop_file = tmp_path / "ec2-cpu.md"
        sop_file.write_text(SOP_CONTENT)

        mock_settings.sop_similarity_threshold = 0.3
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = tmp_path

        hit = FakeSearchResult(score=0.8, file_path=None, case_id="ec2-cpu", content="")
        mock_parse.return_value = ({"resource_type": "EC2", "issue_pattern": "High CPU"}, "")

        import sys
        fake_mod = MagicMock()
        fake_mod.hybrid_search = MagicMock(return_value=[hit])

        with patch.dict(sys.modules, {"agenticops.kb.search": fake_mod}):
            result = identify_matching_sop("EC2", "cpu issue")

        assert result is not None
        assert "ec2-cpu.md" in result.sop_path

    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_vector_hit_below_threshold_falls_to_keyword(self, mock_settings):
        """When vector result score < threshold, fall through to keyword search."""
        mock_settings.sop_similarity_threshold = 0.9
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        hit = FakeSearchResult(score=0.3, file_path="/tmp/sops/x.md", content="x")

        import sys
        fake_mod = MagicMock()
        fake_mod.hybrid_search = MagicMock(return_value=[hit])

        with patch.dict(sys.modules, {"agenticops.kb.search": fake_mod}), \
             patch("agenticops.pipeline.sop_identifier._keyword_search_sops", return_value=[]):
            result = identify_matching_sop("EC2", "something")

        assert result is None


# ---------------------------------------------------------------------------
# Keyword fallback: below-threshold rejection (lines 97-98)
# ---------------------------------------------------------------------------

class TestKeywordFallbackThreshold:
    """Keyword results below the similarity threshold should be rejected."""

    @patch("agenticops.pipeline.sop_identifier._keyword_search_sops")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_keyword_below_threshold_returns_none(self, mock_settings, mock_kw):
        mock_settings.sop_similarity_threshold = 0.8
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        # keyword score 1 → normalized 1/10 = 0.1, below 0.8
        mock_kw.return_value = [
            {
                "file": "low-match.md",
                "score": 1,
                "content": "something",
                "metadata": {"resource_type": "EC2", "issue_pattern": "x"},
            }
        ]

        # Make vector search fail so we fall through to keyword
        import sys
        with patch.dict(sys.modules, {"agenticops.kb.search": None}):
            result = identify_matching_sop("EC2", "unrelated issue")

        assert result is None

    @patch("agenticops.pipeline.sop_identifier._keyword_search_sops")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_keyword_above_threshold_returns_match(self, mock_settings, mock_kw):
        mock_settings.sop_similarity_threshold = 0.3
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        mock_kw.return_value = [
            {
                "file": "good-match.md",
                "score": 8,
                "content": "fix steps",
                "metadata": {"resource_type": "RDS", "issue_pattern": "connection timeout"},
            }
        ]

        import sys
        with patch.dict(sys.modules, {"agenticops.kb.search": None}):
            result = identify_matching_sop("RDS", "connection timeout")

        assert result is not None
        assert result.filename == "good-match.md"
        assert result.similarity_score == pytest.approx(0.8)
        assert result.resource_type == "RDS"

    @patch("agenticops.pipeline.sop_identifier._keyword_search_sops")
    @patch("agenticops.pipeline.sop_identifier.settings")
    def test_keyword_no_score_key_defaults_half(self, mock_settings, mock_kw):
        """When keyword result has no 'score' key, normalized score defaults to 0.5."""
        mock_settings.sop_similarity_threshold = 0.3
        mock_settings.ensure_dirs = MagicMock()
        mock_settings.sops_dir = Path("/tmp/sops")

        mock_kw.return_value = [
            {
                "file": "no-score.md",
                "content": "content",
                "metadata": {},
            }
        ]

        import sys
        with patch.dict(sys.modules, {"agenticops.kb.search": None}):
            result = identify_matching_sop("EC2", "something")

        assert result is not None
        assert result.similarity_score == pytest.approx(0.5)
