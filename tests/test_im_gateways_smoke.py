"""IM Gateway smoke tests — mock-based happy-path for DingTalk, Feishu, Slack, WeCom.

P2 task: ensure basic verify_callback + parse_message work without external deps.
"""

from unittest.mock import patch, MagicMock
import pytest


# ---------------------------------------------------------------------------
# DingTalk Gateway
# ---------------------------------------------------------------------------

class TestDingTalkGateway:
    """Smoke tests for DingTalkGateway."""

    @patch("agenticops.im.dingtalk_gateway.get_dingtalk_app", return_value=None)
    def test_verify_callback_no_config(self, mock_app):
        from agenticops.im.dingtalk_gateway import DingTalkGateway
        gw = DingTalkGateway("test")
        # No config → skip verification → True
        assert gw.verify_callback(b"body", {}) is True

    @patch("agenticops.im.dingtalk_gateway.get_dingtalk_app", return_value=None)
    def test_parse_text_message(self, mock_app):
        from agenticops.im.dingtalk_gateway import DingTalkGateway
        gw = DingTalkGateway("test")
        payload = {
            "msgtype": "text",
            "text": {"content": "hello bot"},
            "conversationId": "cid123",
            "senderId": "user1",
            "senderNick": "Alice",
            "conversationType": "2",
            "msgId": "msg001",
        }
        msg = gw.parse_message(payload)
        assert msg is not None
        assert msg.platform == "dingtalk"
        assert msg.content == "hello bot"
        assert msg.chat_id == "cid123"
        assert msg.sender_name == "Alice"
        assert msg.is_group is True

    @patch("agenticops.im.dingtalk_gateway.get_dingtalk_app", return_value=None)
    def test_parse_non_text_returns_none(self, mock_app):
        from agenticops.im.dingtalk_gateway import DingTalkGateway
        gw = DingTalkGateway("test")
        payload = {"msgtype": "image", "text": {}}
        assert gw.parse_message(payload) is None

    @patch("agenticops.im.dingtalk_gateway.get_dingtalk_app", return_value=None)
    def test_parse_empty_content_returns_none(self, mock_app):
        from agenticops.im.dingtalk_gateway import DingTalkGateway
        gw = DingTalkGateway("test")
        payload = {"msgtype": "text", "text": {"content": "   "}}
        assert gw.parse_message(payload) is None


# ---------------------------------------------------------------------------
# Feishu Gateway
# ---------------------------------------------------------------------------

class TestFeishuGateway:
    """Smoke tests for FeishuGateway."""

    @patch("agenticops.im.feishu_gateway.get_feishu_app", return_value=None)
    def test_verify_callback_no_config(self, mock_app):
        from agenticops.im.feishu_gateway import FeishuGateway
        gw = FeishuGateway("test")
        assert gw.verify_callback(b"body", {}) is True

    @patch("agenticops.im.feishu_gateway.get_feishu_app", return_value=None)
    def test_parse_text_message(self, mock_app):
        from agenticops.im.feishu_gateway import FeishuGateway
        gw = FeishuGateway("test")
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_type": "text",
                    "content": '{"text": "deploy status"}',
                    "chat_id": "oc_abc123",
                    "chat_type": "group",
                    "message_id": "om_xxx",
                },
                "sender": {
                    "sender_id": {"user_id": "u_123", "open_id": "ou_456"},
                },
            },
        }
        msg = gw.parse_message(payload)
        assert msg is not None
        assert msg.platform == "feishu"
        assert msg.content == "deploy status"
        assert msg.chat_id == "oc_abc123"
        assert msg.is_group is True

    @patch("agenticops.im.feishu_gateway.get_feishu_app", return_value=None)
    def test_parse_url_verification_returns_none(self, mock_app):
        from agenticops.im.feishu_gateway import FeishuGateway
        gw = FeishuGateway("test")
        payload = {"type": "url_verification", "challenge": "abc"}
        assert gw.parse_message(payload) is None

    @patch("agenticops.im.feishu_gateway.get_feishu_app", return_value=None)
    def test_is_challenge(self, mock_app):
        from agenticops.im.feishu_gateway import FeishuGateway
        assert FeishuGateway.is_challenge({"type": "url_verification"}) is True
        assert FeishuGateway.is_challenge({"type": "event_callback"}) is False

    @patch("agenticops.im.feishu_gateway.get_feishu_app", return_value=None)
    def test_parse_non_text_returns_none(self, mock_app):
        from agenticops.im.feishu_gateway import FeishuGateway
        gw = FeishuGateway("test")
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {"message_type": "image", "content": "{}"},
                "sender": {"sender_id": {}},
            },
        }
        assert gw.parse_message(payload) is None


# ---------------------------------------------------------------------------
# Slack Gateway
# ---------------------------------------------------------------------------

class TestSlackGateway:
    """Smoke tests for SlackGateway."""

    @patch("agenticops.im.slack_gateway.get_slack_app", return_value=None)
    def test_verify_callback_no_config(self, mock_app):
        from agenticops.im.slack_gateway import SlackGateway
        gw = SlackGateway("test")
        assert gw.verify_callback(b"body", {}) is True

    @patch("agenticops.im.slack_gateway.get_slack_app", return_value=None)
    def test_parse_text_message(self, mock_app):
        from agenticops.im.slack_gateway import SlackGateway
        gw = SlackGateway("test")
        payload = {
            "event": {
                "type": "message",
                "text": "<@U123> check pods",
                "channel": "C999",
                "user": "U456",
                "ts": "1700000000.000001",
            }
        }
        msg = gw.parse_message(payload)
        assert msg is not None
        assert msg.platform == "slack"
        assert msg.content == "check pods"
        assert msg.chat_id == "C999"
        assert msg.sender_id == "U456"

    @patch("agenticops.im.slack_gateway.get_slack_app", return_value=None)
    def test_parse_bot_message_returns_none(self, mock_app):
        from agenticops.im.slack_gateway import SlackGateway
        gw = SlackGateway("test")
        payload = {
            "event": {
                "type": "message",
                "text": "bot reply",
                "bot_id": "B123",
                "channel": "C999",
                "user": "U456",
                "ts": "1700000000.000002",
            }
        }
        assert gw.parse_message(payload) is None

    @patch("agenticops.im.slack_gateway.get_slack_app", return_value=None)
    def test_parse_subtype_returns_none(self, mock_app):
        from agenticops.im.slack_gateway import SlackGateway
        gw = SlackGateway("test")
        payload = {
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "text": "edited",
                "channel": "C999",
                "user": "U456",
                "ts": "1700000000.000003",
            }
        }
        assert gw.parse_message(payload) is None

    @patch("agenticops.im.slack_gateway.get_slack_app", return_value=None)
    def test_is_challenge(self, mock_app):
        from agenticops.im.slack_gateway import SlackGateway
        assert SlackGateway.is_challenge({"type": "url_verification", "challenge": "x"}) is True
        assert SlackGateway.is_challenge({"type": "event_callback"}) is False


# ---------------------------------------------------------------------------
# WeCom Gateway
# ---------------------------------------------------------------------------

class TestWeComGateway:
    """Smoke tests for WeComGateway."""

    @patch("agenticops.im.wecom_gateway.get_wecom_app", return_value=None)
    def test_verify_callback_no_config(self, mock_app):
        from agenticops.im.wecom_gateway import WeComGateway
        gw = WeComGateway("test")
        assert gw.verify_callback(b"<xml></xml>", {}) is True

    @patch("agenticops.im.wecom_gateway.get_wecom_app", return_value=None)
    def test_parse_empty_xml_body_returns_none(self, mock_app):
        from agenticops.im.wecom_gateway import WeComGateway
        gw = WeComGateway("test")
        assert gw.parse_message({"xml_body": ""}) is None
        assert gw.parse_message({}) is None

    @patch("agenticops.im.wecom_gateway.get_wecom_app")
    def test_parse_message_no_encrypt_returns_none(self, mock_app):
        """If XML has no Encrypt element, returns None."""
        from agenticops.im.wecom_gateway import WeComGateway
        mock_app.return_value = None
        gw = WeComGateway("test")
        payload = {"xml_body": "<xml><ToUserName>corp</ToUserName></xml>"}
        assert gw.parse_message(payload) is None

    def test_pkcs7_unpad(self):
        from agenticops.im.wecom_gateway import _pkcs7_unpad
        # Standard PKCS#7 padding with pad=4
        data = b"hello" + bytes([4, 4, 4, 4])
        assert _pkcs7_unpad(data) == b"hello"

    def test_pkcs7_unpad_invalid(self):
        from agenticops.im.wecom_gateway import _pkcs7_unpad
        # pad > 32 → returns data unchanged
        data = b"hello" + bytes([33])
        assert _pkcs7_unpad(data) == data
