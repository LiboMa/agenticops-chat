"""Tests for IM WebSocket services: Feishu WS, Slack WS, session manager, alert routing."""

import logging
import re
import threading
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# _build_agent_input — alert context builder
# ============================================================================


class TestBuildAgentInput:
    """Test _build_agent_input alert channel wrapping logic."""

    def _make_channel(self, name, chat_id, ctype="feishu", role="chat", alert_senders=None):
        from agenticops.notify.im_config import ChannelConfig
        return ChannelConfig(
            name=name, channel_type=ctype,
            config={"chat_id": chat_id}, role=role,
            alert_senders=alert_senders or [],
        )

    def test_alert_channel_wraps_with_prompt(self):
        from agenticops.im.feishu_ws import _build_agent_input
        ch = self._make_channel("feishu-alert", "oc_alert", role="alert")
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("CPU at 99%", "feishu", "oc_alert", "user1")
            assert "<im_alert_context>" in result
            assert "CPU at 99%" in result
            assert "STEP 1" in result

    def test_chat_channel_no_wrap(self):
        from agenticops.im.feishu_ws import _build_agent_input
        ch = self._make_channel("feishu-ops", "oc_chat", role="chat")
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("hello", "feishu", "oc_chat", "user1")
            assert result == "hello"

    def test_alert_sender_wraps(self):
        from agenticops.im.feishu_ws import _build_agent_input
        ch = self._make_channel("shared", "oc_shared", role="chat", alert_senders=["bot_prom"])
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("firing", "feishu", "oc_shared", "bot_prom")
            assert "<im_alert_context>" in result

    def test_event_driven_mode_no_wrap(self):
        from agenticops.im.feishu_ws import _build_agent_input
        with patch("agenticops.im.feishu_ws.settings") as ms:
            ms.alert_pipeline_mode = "event_driven"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("ALARM", "feishu", "oc_alert", "")
            assert result == "ALARM"

    def test_detection_disabled_no_wrap(self):
        from agenticops.im.feishu_ws import _build_agent_input
        with patch("agenticops.im.feishu_ws.settings") as ms:
            ms.im_alert_detection_enabled = False
            result = _build_agent_input("ALARM: test", "feishu", "oc_alert", "")
            assert result == "ALARM: test"

    def test_unknown_channel_no_wrap(self):
        from agenticops.im.feishu_ws import _build_agent_input
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[]):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("hello", "slack", "C_UNKNOWN", "U1")
            assert result == "hello"

    def test_slack_alert_channel_wraps(self):
        from agenticops.im.feishu_ws import _build_agent_input
        ch = self._make_channel("slack-alert", "C_ALERT", ctype="slack", role="alert")
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            result = _build_agent_input("CPU 99%", "slack", "C_ALERT", "U1")
            assert "<im_alert_context>" in result

    def test_prompt_has_5_steps(self):
        from agenticops.im.feishu_ws import _ALERT_CHANNEL_PROMPT
        prompt = _ALERT_CHANNEL_PROMPT.format(channel_name="test", platform="feishu")
        for step in ("STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5"):
            assert step in prompt
        assert "create_health_issue" in prompt


# ============================================================================
# Slack WS _on_event — event filtering
# ============================================================================


class TestSlackOnEvent:
    """Test Slack WS event handler filtering logic."""

    def _make_service(self):
        with patch("agenticops.im.slack_ws.get_slack_app") as mock_get:
            mock_app = MagicMock()
            mock_app.app_token = "xapp-test"
            mock_app.bot_token = "xoxb-test"
            mock_app.respond_to = "mentions_only"
            mock_get.return_value = mock_app

            with patch("agenticops.im.slack_ws.SocketModeClient"), \
                 patch("agenticops.im.slack_ws.WebClient"):
                from agenticops.im.slack_ws import SlackWSService
                svc = SlackWSService.__new__(SlackWSService)
                svc._app_name = "default"
                svc._app_config = mock_app
                svc._im_sessions = MagicMock()
                svc._thread = None
                svc._started = False
                svc._bot_user_id = "UBOT12345"
                svc._respond_to = "mentions_only"
                svc._chat_locks = defaultdict(threading.Lock)
                svc._web_client = MagicMock()
                svc._socket_client = MagicMock()
                return svc

    def _make_req(self, text, channel="C123", user="U_USER", bot_id=None, subtype=None):
        event = {"type": "message", "text": text, "channel": channel, "user": user, "ts": "123.456"}
        if bot_id:
            event["bot_id"] = bot_id
        if subtype:
            event["subtype"] = subtype
        req = MagicMock()
        req.type = "events_api"
        req.envelope_id = "env-1"
        req.payload = {"event": event}
        return req

    def test_ignores_non_events_api(self):
        svc = self._make_service()
        req = MagicMock()
        req.type = "slash_commands"
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_not_called()

    def test_ignores_message_subtypes(self):
        svc = self._make_service()
        req = self._make_req("edit", subtype="message_changed")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_not_called()

    def test_ignores_own_messages(self):
        svc = self._make_service()
        req = self._make_req("hello", user="UBOT12345")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_not_called()

    def test_ignores_bot_without_mention(self):
        svc = self._make_service()
        req = self._make_req("alert firing", bot_id="B_ALERT")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_not_called()

    def test_accepts_bot_with_mention(self):
        svc = self._make_service()
        req = self._make_req("<@UBOT12345> check this alert", bot_id="B_ALERT")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_called_once()
            args = pool.submit.call_args[0]
            assert args[5] is True  # was_mentioned

    def test_accepts_mention_in_normal_channel(self):
        svc = self._make_service()
        req = self._make_req("<@UBOT12345> what is going on?")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_called_once()

    def test_rejects_no_mention_in_normal_channel(self):
        svc = self._make_service()
        req = self._make_req("hello world")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool, \
             patch("agenticops.notify.im_config.load_channels", return_value=[]):
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_not_called()

    def test_accepts_no_mention_in_alert_channel(self):
        from agenticops.notify.im_config import ChannelConfig
        svc = self._make_service()
        req = self._make_req("CPU 99% CRITICAL", channel="C_ALERT")
        alert_ch = ChannelConfig(
            name="slack-alert", channel_type="slack",
            config={"chat_id": "C_ALERT"}, role="alert",
        )
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool, \
             patch("agenticops.notify.im_config.load_channels", return_value=[alert_ch]):
            svc._on_event(svc._socket_client, req)
            pool.submit.assert_called_once()
            args = pool.submit.call_args[0]
            assert args[5] is False  # was_mentioned=False

    def test_strips_mentions_from_text(self):
        svc = self._make_service()
        req = self._make_req("<@UBOT12345> check health")
        with patch("agenticops.im.slack_ws._AGENT_POOL") as pool:
            svc._on_event(svc._socket_client, req)
            args = pool.submit.call_args[0]
            # args: (func, channel, text, message_id, user, has_mention)
            text_arg = args[2]
            assert "<@UBOT12345>" not in text_arg
            assert "check health" in text_arg


# ============================================================================
# Slack _process_and_reply — alert wrapping
# ============================================================================


class TestSlackProcessAndReply:
    """Verify _process_and_reply alert wrapping behavior."""

    def _make_service(self):
        with patch("agenticops.im.slack_ws.get_slack_app") as mock_get:
            mock_app = MagicMock()
            mock_app.app_token = "xapp-test"
            mock_app.bot_token = "xoxb-test"
            mock_app.respond_to = "mentions_only"
            mock_get.return_value = mock_app

            with patch("agenticops.im.slack_ws.SocketModeClient"), \
                 patch("agenticops.im.slack_ws.WebClient"):
                from agenticops.im.slack_ws import SlackWSService
                svc = SlackWSService.__new__(SlackWSService)
                svc._app_name = "default"
                svc._app_config = mock_app
                svc._im_sessions = MagicMock()
                svc._thread = None
                svc._started = False
                svc._bot_user_id = "UBOT12345"
                svc._respond_to = "mentions_only"
                svc._chat_locks = defaultdict(threading.Lock)
                svc._web_client = MagicMock()
                svc._socket_client = MagicMock()
                return svc

    def test_mentioned_alert_gets_context_prompt(self):
        """Mentioned messages in alert channels get alert prompt + history."""
        from agenticops.notify.im_config import ChannelConfig
        svc = self._make_service()
        mock_agent = MagicMock(return_value="Analyzing...")
        svc._im_sessions.get_or_create.return_value = mock_agent
        svc._fetch_channel_context = MagicMock(return_value="<channel_history>\n[BOT] alert\n</channel_history>\n\n")

        alert_ch = ChannelConfig(
            name="slack-alert", channel_type="slack",
            config={"chat_id": "C_ALERT"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[alert_ch]), \
             patch("agenticops.config.set_im_origin"), \
             patch("agenticops.config.set_trace_id"), \
             patch("agenticops.config.generate_trace_id", return_value="TRC-test1234"):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            svc._process_and_reply("C_ALERT", "check this", "123.456", "U_USER", was_mentioned=True)
            agent_call_args = mock_agent.call_args[0][0]
            assert "<im_alert_context>" in agent_call_args
            assert "<channel_history>" in agent_call_args
            assert "check this" in agent_call_args

    def test_non_mentioned_alert_channel_bug(self):
        """BUG: non-mentioned messages in alert channels currently SKIP _build_agent_input.

        This test documents the known bug — non-mentioned messages in alert
        channels reach the agent as raw text without alert context wrapping.
        """
        from agenticops.notify.im_config import ChannelConfig
        svc = self._make_service()
        mock_agent = MagicMock(return_value="ok")
        svc._im_sessions.get_or_create.return_value = mock_agent

        alert_ch = ChannelConfig(
            name="slack-alert", channel_type="slack",
            config={"chat_id": "C_ALERT"}, role="alert",
        )
        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[alert_ch]), \
             patch("agenticops.config.set_im_origin"), \
             patch("agenticops.config.set_trace_id"), \
             patch("agenticops.config.generate_trace_id", return_value="TRC-test1234"):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            svc._process_and_reply("C_ALERT", "CPU 99%", "123.456", "U_USER", was_mentioned=False)
            agent_call_args = mock_agent.call_args[0][0]
            # BUG: this SHOULD have <im_alert_context> but currently doesn't
            # When fixed, change this assertion to: assert "<im_alert_context>" in agent_call_args
            assert agent_call_args == "CPU 99%"

    def test_normal_channel_no_wrap(self):
        svc = self._make_service()
        mock_agent = MagicMock(return_value="Hello!")
        svc._im_sessions.get_or_create.return_value = mock_agent

        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[]), \
             patch("agenticops.config.set_im_origin"), \
             patch("agenticops.config.set_trace_id"), \
             patch("agenticops.config.generate_trace_id", return_value="TRC-test1234"):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            svc._process_and_reply("C_OPS", "hi there", "123.456", "U_USER", was_mentioned=True)
            agent_call_args = mock_agent.call_args[0][0]
            assert "<im_alert_context>" not in agent_call_args

    def test_send_to_intercepted(self):
        svc = self._make_service()
        with patch("agenticops.chat.send_to.execute_send_to") as mock_send:
            mock_send.return_value = MagicMock(message="Sent!")
            svc._process_and_reply("C_OPS", "/send_to ops hello", "123.456", "U_USER", was_mentioned=True)
            mock_send.assert_called_once()

    def test_sets_im_origin_and_trace_id(self):
        svc = self._make_service()
        mock_agent = MagicMock(return_value="ok")
        svc._im_sessions.get_or_create.return_value = mock_agent

        with patch("agenticops.im.feishu_ws.settings") as ms, \
             patch("agenticops.notify.im_config.load_channels", return_value=[]), \
             patch("agenticops.config.set_im_origin") as mock_origin, \
             patch("agenticops.config.set_trace_id") as mock_trace, \
             patch("agenticops.config.generate_trace_id", return_value="TRC-aaaa0000"):
            ms.alert_pipeline_mode = "both"
            ms.im_alert_detection_enabled = True
            svc._process_and_reply("C_OPS", "hello", "123.456", "U_USER", was_mentioned=True)

            assert mock_origin.call_count == 2
            mock_origin.assert_any_call({"platform": "slack", "chat_id": "C_OPS"})
            mock_origin.assert_any_call(None)
            assert mock_trace.call_count == 2
            mock_trace.assert_any_call("TRC-aaaa0000")
            mock_trace.assert_any_call(None)


# ============================================================================
# Session Manager
# ============================================================================


class TestIMChatSessionManager:
    """Test per-chat agent session management."""

    def test_creates_new_agent(self):
        with patch("agenticops.im.session_manager.create_main_agent") as mock_create:
            mock_agent = MagicMock()
            mock_create.return_value = mock_agent
            from agenticops.im.session_manager import IMChatSessionManager
            mgr = IMChatSessionManager()
            agent = mgr.get_or_create("feishu", "oc_123")
            assert agent is mock_agent
            mock_create.assert_called_once()

    def test_reuses_existing_agent(self):
        with patch("agenticops.im.session_manager.create_main_agent") as mock_create:
            mock_agent = MagicMock()
            mock_create.return_value = mock_agent
            from agenticops.im.session_manager import IMChatSessionManager
            mgr = IMChatSessionManager()
            a1 = mgr.get_or_create("feishu", "oc_123")
            a2 = mgr.get_or_create("feishu", "oc_123")
            assert a1 is a2
            assert mock_create.call_count == 1

    def test_different_chats_get_different_agents(self):
        with patch("agenticops.im.session_manager.create_main_agent") as mock_create:
            mock_create.side_effect = [MagicMock(), MagicMock()]
            from agenticops.im.session_manager import IMChatSessionManager
            mgr = IMChatSessionManager()
            a1 = mgr.get_or_create("feishu", "oc_1")
            a2 = mgr.get_or_create("feishu", "oc_2")
            assert a1 is not a2

    def test_different_platforms_get_different_agents(self):
        with patch("agenticops.im.session_manager.create_main_agent") as mock_create:
            mock_create.side_effect = [MagicMock(), MagicMock()]
            from agenticops.im.session_manager import IMChatSessionManager
            mgr = IMChatSessionManager()
            a1 = mgr.get_or_create("feishu", "ch_same")
            a2 = mgr.get_or_create("slack", "ch_same")
            assert a1 is not a2

    def test_remove_clears_session(self):
        with patch("agenticops.im.session_manager.create_main_agent") as mock_create:
            mock_create.side_effect = [MagicMock(), MagicMock()]
            from agenticops.im.session_manager import IMChatSessionManager
            mgr = IMChatSessionManager()
            a1 = mgr.get_or_create("feishu", "oc_1")
            mgr.remove("feishu", "oc_1")
            a2 = mgr.get_or_create("feishu", "oc_1")
            assert a1 is not a2


# ============================================================================
# Mention regex patterns
# ============================================================================


class TestSlackMentionRegex:
    def test_strips_single(self):
        from agenticops.im.slack_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "<@U12345ABC> check health").strip() == "check health"

    def test_strips_multiple(self):
        from agenticops.im.slack_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "<@U1> <@U2> hello").strip() == "hello"

    def test_preserves_plain(self):
        from agenticops.im.slack_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "no mentions here").strip() == "no mentions here"

    def test_empty_after_strip(self):
        from agenticops.im.slack_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "<@U12345ABC>  ").strip() == ""


class TestFeishuMentionRegex:
    def test_strips_feishu_mention(self):
        from agenticops.im.feishu_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "@_user_1 check this").strip() == "check this"

    def test_strips_multiple(self):
        from agenticops.im.feishu_ws import _MENTION_RE
        assert _MENTION_RE.sub("", "@_user_1 @_user_2 hello").strip() == "hello"


# ============================================================================
# find_channel_by_chat
# ============================================================================


class TestFindChannelByChat:
    def test_finds_matching(self):
        from agenticops.notify.im_config import ChannelConfig, find_channel_by_chat
        ch = ChannelConfig(name="feishu-alert", channel_type="feishu",
                           config={"chat_id": "oc_alert"}, role="alert")
        with patch("agenticops.notify.im_config.load_channels", return_value=[ch]):
            result = find_channel_by_chat("feishu", "oc_alert")
            assert result is not None
            assert result.name == "feishu-alert"
            assert result.role == "alert"

    def test_returns_none_for_unknown(self):
        from agenticops.notify.im_config import find_channel_by_chat
        with patch("agenticops.notify.im_config.load_channels", return_value=[]):
            assert find_channel_by_chat("slack", "C_UNKNOWN") is None

    def test_matches_platform_and_chat_id(self):
        from agenticops.notify.im_config import ChannelConfig, find_channel_by_chat
        feishu_ch = ChannelConfig(name="f-ch", channel_type="feishu", config={"chat_id": "oc_123"})
        slack_ch = ChannelConfig(name="s-ch", channel_type="slack", config={"chat_id": "C_123"})
        with patch("agenticops.notify.im_config.load_channels", return_value=[feishu_ch, slack_ch]):
            assert find_channel_by_chat("feishu", "oc_123").name == "f-ch"
            assert find_channel_by_chat("slack", "C_123").name == "s-ch"
            assert find_channel_by_chat("feishu", "C_123") is None
