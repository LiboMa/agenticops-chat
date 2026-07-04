"""Tests for src/agenticops/services/model_service.py — 0% → target 90%+."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agenticops.services import model_service
from agenticops.services.model_service import (
    _build_presets_from_bedrock,
    _fetch_bedrock_models,
    _get_fallback_presets,
    get_model_presets,
    invalidate_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure cache is clean before/after each test."""
    invalidate_cache()
    yield
    invalidate_cache()


SAMPLE_BEDROCK_RESPONSE = {
    "modelSummaries": [
        {
            "modelId": "anthropic.claude-opus-4-6-v1",
            "modelName": "Claude Opus 4.6",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND", "STREAMING"],
        },
        {
            "modelId": "anthropic.claude-sonnet-4-5-v1",
            "modelName": "Claude Sonnet 4.5",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND", "STREAMING"],
        },
        {
            "modelId": "anthropic.claude-haiku-4-5-v1",
            "modelName": "Claude Haiku 4.5",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
        # Should be filtered out: non-TEXT output
        {
            "modelId": "anthropic.claude-embed-v1",
            "modelName": "Claude Embed",
            "outputModalities": ["EMBEDDING"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
        # Should be filtered out: not ACTIVE
        {
            "modelId": "anthropic.claude-sonnet-3-5-v1",
            "modelName": "Claude Sonnet 3.5",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "LEGACY"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
        # Should be filtered out: non-Claude model
        {
            "modelId": "anthropic.titan-text-v1",
            "modelName": "Titan Text",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
    ]
}


# ---------------------------------------------------------------------------
# _fetch_bedrock_models
# ---------------------------------------------------------------------------

class TestFetchBedrockModels:
    def test_fetches_and_filters_correctly(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models("us-east-1")

        # Should include 3 Claude TEXT/ACTIVE models, exclude embed, legacy, non-claude
        assert len(models) == 3
        ids = [m["model_id"] for m in models]
        assert "anthropic.claude-opus-4-6-v1" in ids
        assert "anthropic.claude-sonnet-4-5-v1" in ids
        assert "anthropic.claude-haiku-4-5-v1" in ids

    def test_streaming_flag(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        opus = next(m for m in models if "opus" in m["model_id"])
        haiku = next(m for m in models if "haiku" in m["model_id"])
        assert opus["streaming"] is True
        assert haiku["streaming"] is False

    def test_empty_response(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {"modelSummaries": []}

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        assert models == []


# ---------------------------------------------------------------------------
# _build_presets_from_bedrock
# ---------------------------------------------------------------------------

class TestBuildPresetsFromBedrock:
    def test_generates_global_prefixed_ids(self):
        raw = [
            {"model_id": "anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6", "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        assert len(presets) == 1
        assert presets[0]["value"] == "global.anthropic.claude-opus-4-6-v1"
        assert presets[0]["context_window"] == 200000

    def test_does_not_double_prefix_global(self):
        raw = [
            {"model_id": "global.anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6", "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        assert presets[0]["value"] == "global.anthropic.claude-opus-4-6-v1"

    def test_deduplicates_models(self):
        raw = [
            {"model_id": "anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6", "context_window": 0, "streaming": True},
            {"model_id": "anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6", "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        assert len(presets) == 1

    def test_sort_order_opus_first(self):
        raw = [
            {"model_id": "anthropic.claude-haiku-4-5-v1", "model_name": "Claude Haiku 4.5", "context_window": 0, "streaming": False},
            {"model_id": "anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6", "context_window": 0, "streaming": True},
            {"model_id": "anthropic.claude-sonnet-4-5-v1", "model_name": "Claude Sonnet 4.5", "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        labels = [p["label"] for p in presets]
        assert labels[0].startswith("Opus")
        assert labels[1].startswith("Sonnet")
        assert labels[2].startswith("Haiku")

    def test_label_extraction(self):
        raw = [
            {"model_id": "anthropic.claude-sonnet-4-5-v1", "model_name": "Claude Sonnet 4.5", "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        assert presets[0]["label"] == "Sonnet 4.5"

    def test_model_without_version_pattern(self):
        raw = [
            {"model_id": "anthropic.claude-instant-v1", "model_name": "Claude Instant", "context_window": 0, "streaming": False},
        ]
        presets = _build_presets_from_bedrock(raw)
        # Falls back to model_name first word
        assert len(presets) == 1
        assert "Claude" in presets[0]["label"]


# ---------------------------------------------------------------------------
# _get_fallback_presets
# ---------------------------------------------------------------------------

class TestGetFallbackPresets:
    def test_returns_presets_from_settings(self):
        mock_settings = MagicMock()
        mock_settings.model_aliases = {"opus": "global.anthropic.claude-opus-4-6-v1", "sonnet": "global.anthropic.claude-sonnet-4-5-v1"}

        with patch("agenticops.config.settings", mock_settings):
            presets = _get_fallback_presets()

        assert len(presets) == 2
        values = [p["value"] for p in presets]
        assert "global.anthropic.claude-opus-4-6-v1" in values


# ---------------------------------------------------------------------------
# get_model_presets (integration/caching)
# ---------------------------------------------------------------------------

class TestGetModelPresets:
    def test_caching_works(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            result1 = get_model_presets()
            result2 = get_model_presets()

        # Second call should use cache — only one API call
        assert mock_client.list_foundation_models.call_count == 1
        assert result1 == result2

    def test_falls_back_on_api_error(self):
        mock_settings = MagicMock()
        mock_settings.model_aliases = {"opus": "global.anthropic.claude-opus-4-6-v1"}
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", side_effect=Exception("API error")), \
             patch("agenticops.config.settings", mock_settings):
            presets = get_model_presets()

        assert len(presets) >= 1
        assert any("opus" in p["value"].lower() for p in presets)

    def test_falls_back_on_empty_response(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {"modelSummaries": []}

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.model_aliases = {"haiku": "global.anthropic.claude-haiku-4-5-v1"}
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            presets = get_model_presets()

        assert len(presets) >= 1

    def test_custom_models_appended(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.custom_models = [
            {"model_id": "custom.my-model-v1", "label": "Custom Model", "context_window": 128000}
        ]

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            presets = get_model_presets()

        custom = next((p for p in presets if p["value"] == "custom.my-model-v1"), None)
        assert custom is not None
        assert custom["label"] == "Custom Model"
        assert custom["context_window"] == 128000

    def test_deduplicates_by_value(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        # custom model has same value as one from Bedrock
        mock_settings.custom_models = [
            {"model_id": "global.anthropic.claude-opus-4-6-v1", "label": "Duplicate"}
        ]

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            presets = get_model_presets()

        values = [p["value"] for p in presets]
        assert values.count("global.anthropic.claude-opus-4-6-v1") == 1


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------

class TestInvalidateCache:
    def test_invalidate_forces_refresh(self):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = SAMPLE_BEDROCK_RESPONSE

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            get_model_presets()
            invalidate_cache()
            get_model_presets()

        assert mock_client.list_foundation_models.call_count == 2
