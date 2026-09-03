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

OPENAI_BEDROCK_RESPONSE = {
    "modelSummaries": [
        {
            "modelId": "openai.gpt-oss-120b-1:0",
            "modelName": "gpt-oss-120b",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["ON_DEMAND"],
        },
        {
            "modelId": "openai.gpt-5.6-terra",
            "modelName": "GPT-5.6 Terra",
            "outputModalities": ["TEXT"],
            "modelLifecycle": {"status": "ACTIVE"},
            "inferenceTypesSupported": ["INFERENCE_PROFILE"],
        },
    ]
}

OPENAI_PROFILE_RESPONSE = {
    "inferenceProfileSummaries": [
        {"inferenceProfileId": "global.openai.gpt-5.6-terra"},
        {"inferenceProfileId": "us.openai.gpt-5.6-terra"},
    ]
}


def _mock_client(anthropic=None, openai=None):
    """Bedrock client mock answering list_foundation_models per provider."""
    client = MagicMock()

    def _lfm(byProvider):
        if byProvider == "Anthropic":
            return anthropic or {"modelSummaries": []}
        return openai or {"modelSummaries": []}

    client.list_foundation_models.side_effect = _lfm
    client.list_inference_profiles.return_value = OPENAI_PROFILE_RESPONSE
    return client


# ---------------------------------------------------------------------------
# _fetch_bedrock_models
# ---------------------------------------------------------------------------

class TestFetchBedrockModels:
    def test_fetches_and_filters_correctly(self):
        mock_client = _mock_client(anthropic=SAMPLE_BEDROCK_RESPONSE)

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
        mock_client = _mock_client(anthropic=SAMPLE_BEDROCK_RESPONSE)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        opus = next(m for m in models if "opus" in m["model_id"])
        haiku = next(m for m in models if "haiku" in m["model_id"])
        assert opus["streaming"] is True
        assert haiku["streaming"] is False

    def test_empty_response(self):
        mock_client = _mock_client()

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
# OpenAI provider support
# ---------------------------------------------------------------------------

class TestOpenAIModels:
    def test_fetch_includes_openai_with_profile_resolution(self):
        mock_client = _mock_client(anthropic=SAMPLE_BEDROCK_RESPONSE,
                                   openai=OPENAI_BEDROCK_RESPONSE)
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        by_id = {m["model_id"]: m for m in models}
        # ON_DEMAND model invokes by raw id
        assert by_id["openai.gpt-oss-120b-1:0"]["invoke_id"] == "openai.gpt-oss-120b-1:0"
        # INFERENCE_PROFILE-only model resolves to the global system profile
        assert by_id["openai.gpt-5.6-terra"]["invoke_id"] == "global.openai.gpt-5.6-terra"
        # Claude models unaffected
        assert "anthropic.claude-opus-4-6-v1" in by_id

    def test_profile_listing_failure_falls_back_to_global_guess(self):
        mock_client = _mock_client(openai=OPENAI_BEDROCK_RESPONSE)
        mock_client.list_inference_profiles.side_effect = Exception("boom")
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        terra = next(m for m in models if m["model_id"] == "openai.gpt-5.6-terra")
        assert terra["invoke_id"] == "global.openai.gpt-5.6-terra"

    def test_one_provider_failing_keeps_the_other(self):
        mock_client = MagicMock()

        def _lfm(byProvider):
            if byProvider == "Anthropic":
                raise Exception("anthropic listing down")
            return OPENAI_BEDROCK_RESPONSE

        mock_client.list_foundation_models.side_effect = _lfm
        mock_client.list_inference_profiles.return_value = OPENAI_PROFILE_RESPONSE
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session):
            models = _fetch_bedrock_models()

        assert len(models) == 2
        assert all(m["provider"] == "openai" for m in models)

    def test_presets_for_openai_models(self):
        raw = [
            {"model_id": "anthropic.claude-opus-4-6-v1", "model_name": "Claude Opus 4.6",
             "provider": "anthropic", "invoke_id": "anthropic.claude-opus-4-6-v1",
             "context_window": 0, "streaming": True},
            {"model_id": "openai.gpt-oss-120b-1:0", "model_name": "gpt-oss-120b",
             "provider": "openai", "invoke_id": "openai.gpt-oss-120b-1:0",
             "context_window": 0, "streaming": True},
            {"model_id": "openai.gpt-5.6-terra", "model_name": "GPT-5.6 Terra",
             "provider": "openai", "invoke_id": "global.openai.gpt-5.6-terra",
             "context_window": 0, "streaming": True},
        ]
        presets = _build_presets_from_bedrock(raw)
        by_value = {p["value"]: p for p in presets}

        # openai preset uses the resolved invoke id, verbatim label, family window
        assert by_value["openai.gpt-oss-120b-1:0"]["label"] == "gpt-oss-120b"
        assert by_value["openai.gpt-oss-120b-1:0"]["context_window"] == 128000
        assert by_value["global.openai.gpt-5.6-terra"]["label"] == "GPT-5.6 Terra"
        assert by_value["global.openai.gpt-5.6-terra"]["context_window"] == 400000
        # sort: Claude first, then gpt-5.x, then gpt-oss
        values = [p["value"] for p in presets]
        assert values == ["global.anthropic.claude-opus-4-6-v1",
                          "global.openai.gpt-5.6-terra",
                          "openai.gpt-oss-120b-1:0"]


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
        mock_client = _mock_client(anthropic=SAMPLE_BEDROCK_RESPONSE)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            result1 = get_model_presets()
            result2 = get_model_presets()

        # Second call should use cache — one API call per provider (Anthropic + OpenAI)
        assert mock_client.list_foundation_models.call_count == 2
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
        mock_client = _mock_client(anthropic=SAMPLE_BEDROCK_RESPONSE)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        mock_settings = MagicMock()
        mock_settings.custom_models = []

        with patch("agenticops.config.get_bedrock_boto_session", return_value=mock_session), \
             patch("agenticops.config.settings", mock_settings):
            get_model_presets()
            invalidate_cache()
            get_model_presets()

        # 2 fetches × 2 providers (Anthropic + OpenAI)
        assert mock_client.list_foundation_models.call_count == 4
