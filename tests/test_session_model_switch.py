"""Per-session model switch — column, PATCH validation, 409 stream guard."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from agenticops.web.app import app, _streaming_sessions


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def session_id(client):
    r = client.post("/api/chat/sessions", json={})
    assert r.status_code in (200, 201)
    return r.json()["session_id"]


PRESETS = [{"label": "Opus 4.8", "value": "global.anthropic.claude-opus-4-8", "context_window": 200000}]


class TestPatchModelId:
    def test_set_valid_model_persists_and_echoes(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            r = client.patch(f"/api/chat/sessions/{session_id}",
                             json={"model_id": "global.anthropic.claude-opus-4-8"})
        assert r.status_code == 200
        assert r.json()["model_id"] == "global.anthropic.claude-opus-4-8"
        # persisted — list endpoint echoes it too
        rows = client.get("/api/chat/sessions").json()
        mine = [s for s in rows if s["session_id"] == session_id][0]
        assert mine["model_id"] == "global.anthropic.claude-opus-4-8"

    def test_alias_value_accepted(self, client, session_id):
        from agenticops.config import MODEL_ALIASES
        if not MODEL_ALIASES:
            pytest.skip("no aliases configured")
        target = next(iter(MODEL_ALIASES.values()))
        with patch("agenticops.web.app.get_model_presets", return_value=[]):
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": target})
        assert r.status_code == 200

    def test_unknown_model_400(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            r = client.patch(f"/api/chat/sessions/{session_id}",
                             json={"model_id": "not.a.real.model"})
        assert r.status_code == 400

    def test_empty_string_means_auto_stored_null(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": ""})
        assert r.status_code == 200
        assert r.json()["model_id"] is None

    def test_omitted_field_unchanged(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"name": "renamed"})
        assert r.json()["model_id"] == "global.anthropic.claude-opus-4-8"

    def test_streaming_session_409(self, client, session_id):
        _streaming_sessions.add(session_id)
        try:
            with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
                r = client.patch(f"/api/chat/sessions/{session_id}",
                                 json={"model_id": "global.anthropic.claude-opus-4-8"})
            assert r.status_code == 409
        finally:
            _streaming_sessions.discard(session_id)

    def test_streaming_session_allows_non_model_patch(self, client, session_id):
        _streaming_sessions.add(session_id)
        try:
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"pinned": True})
            assert r.status_code == 200
        finally:
            _streaming_sessions.discard(session_id)

    def test_model_change_evicts_only_this_session(self, client, session_id):
        with patch("agenticops.web.app._chat_sessions") as mock_mgr, \
             patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            mock_mgr.remove.assert_called_once_with(session_id)
            mock_mgr.clear.assert_not_called()


class TestModelResolution:
    def test_create_main_agent_accepts_override(self):
        import inspect
        from agenticops.agents.main_agent import create_main_agent
        assert "model_id_override" in inspect.signature(create_main_agent).parameters

    def test_get_or_create_passes_session_model(self, client, session_id):
        from agenticops.web import session_manager as sm
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
        with patch.object(sm, "create_main_agent") as mock_create:
            mock_create.return_value.messages = []
            from agenticops.web.app import _chat_sessions
            _chat_sessions.remove(session_id)
            _chat_sessions.get_or_create(session_id)
            mock_create.assert_called_once_with(model_id_override="global.anthropic.claude-opus-4-8")
            _chat_sessions.remove(session_id)

    def test_auto_session_passes_empty_override(self, client, session_id):
        from agenticops.web import session_manager as sm
        with patch.object(sm, "create_main_agent") as mock_create:
            mock_create.return_value.messages = []
            from agenticops.web.app import _chat_sessions
            _chat_sessions.remove(session_id)
            _chat_sessions.get_or_create(session_id)
            mock_create.assert_called_once_with(model_id_override="")
            _chat_sessions.remove(session_id)


class TestEffectiveModelForCost:
    def test_effective_model_uses_override(self, client, session_id):
        from agenticops.web.app import _effective_main_model
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
        assert _effective_main_model(session_id) == "global.anthropic.claude-opus-4-8"

    def test_effective_model_auto_falls_back_to_global(self, client, session_id):
        from agenticops.web.app import _effective_main_model
        from agenticops.config import get_agent_model_config
        assert _effective_main_model(session_id) == get_agent_model_config("main")[0]
