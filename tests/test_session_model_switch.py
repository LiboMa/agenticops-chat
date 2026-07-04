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
