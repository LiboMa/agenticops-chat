"""建议 chips — 标记块解析纯函数。"""

from agenticops.chat.suggestions import SUGGEST_MARKER, extract_suggestions


class TestExtractSuggestions:
    def test_normal_block(self):
        text = '结论如上。\n<<SUGGEST>>["深入分析 I#42", "扫描同区域 LB", "生成修复计划"]'
        clean, sugs = extract_suggestions(text)
        assert clean == "结论如上。"
        assert sugs == ["深入分析 I#42", "扫描同区域 LB", "生成修复计划"]

    def test_no_marker_returns_original(self):
        clean, sugs = extract_suggestions("plain reply")
        assert clean == "plain reply"
        assert sugs == []

    def test_malformed_json_strips_line_empty_suggestions(self):
        text = "body\n<<SUGGEST>>[broken json"
        clean, sugs = extract_suggestions(text)
        assert clean == "body"
        assert sugs == []

    def test_caps_at_three_and_60_chars(self):
        long = "x" * 100
        text = f'b\n<<SUGGEST>>["{long}", "a", "b", "c", "d"]'
        clean, sugs = extract_suggestions(text)
        assert len(sugs) == 3
        assert len(sugs[0]) == 60

    def test_last_marker_wins(self):
        text = '<<SUGGEST>>["old"]\nbody\n<<SUGGEST>>["new"]'
        clean, sugs = extract_suggestions(text)
        assert sugs == ["new"]
        assert "old" not in "".join(sugs)

    def test_empty_items_dropped_and_trailing_text_tolerated(self):
        text = 'b\n<<SUGGEST>>["", "  ok  "] trailing'
        clean, sugs = extract_suggestions(text)
        assert sugs == ["ok"]

    def test_empty_text(self):
        assert extract_suggestions("") == ("", [])


import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from agenticops.web.app import app
    return TestClient(app)


class TestPersistenceLayer:
    def test_chat_message_has_suggestions_column(self):
        from agenticops.models import ChatMessage
        assert hasattr(ChatMessage, "suggestions")

    def test_messages_api_echoes_suggestions(self, client):
        from agenticops.models import ChatMessage, ChatSession, get_db_session
        r = client.post("/api/chat/sessions", json={})
        sid = r.json()["session_id"]
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
            db.add(ChatMessage(session_id=row.id, role="assistant",
                               content="hi", suggestions=["next step"]))
        msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
        assert msgs[-1]["suggestions"] == ["next step"]
        client.delete(f"/api/chat/sessions/{sid}")

    def test_response_schema_has_field(self):
        from agenticops.web.schemas import ChatMessageResponse
        assert "suggestions" in ChatMessageResponse.model_fields
