"""DingTalk (钉钉) IM Gateway — HTTP callback / Stream mode."""

import hashlib
import hmac
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agenticops.im.gateway import IMGateway, IMInboundMessage
from agenticops.notify.im_config import get_dingtalk_app

logger = logging.getLogger(__name__)


class DingTalkGateway(IMGateway):
    """DingTalk webhook callback gateway.

    Handles text messages from DingTalk group robot callbacks.
    Supports signature verification via timestamp + sign.
    """

    platform = "dingtalk"

    def __init__(self, app_name: str = "default"):
        self.app_name = app_name
        self._app_config = get_dingtalk_app(app_name)

    def verify_callback(self, request_body: bytes, headers: Dict[str, str]) -> bool:
        """Verify DingTalk callback signature.

        DingTalk sends timestamp and sign in headers:
          sign = Base64(HMAC-SHA256(timestamp + "\\n" + app_secret))
        If no app_secret is configured, skip verification.
        """
        if not self._app_config or not self._app_config.app_secret:
            return True

        timestamp = headers.get("timestamp", "")
        sign = headers.get("sign", "")
        if not timestamp or not sign:
            return True  # Missing headers — allow (dev mode)

        string_to_sign = f"{timestamp}\n{self._app_config.app_secret}"
        hmac_code = hmac.new(
            self._app_config.app_secret.encode(),
            string_to_sign.encode(),
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(hmac_code).decode()
        return hmac.compare_digest(expected, sign)

    def parse_message(self, payload: Dict[str, Any]) -> Optional[IMInboundMessage]:
        """Parse DingTalk callback payload into IMInboundMessage.

        DingTalk robot callback format:
        {
            "msgtype": "text",
            "text": {"content": "..."},
            "conversationId": "cidXXX",
            "senderId": "...",
            "senderNick": "...",
            "isInAtList": true,
            "chatbotUserId": "...",
            "conversationType": "2",  // 1=单聊, 2=群聊
            "msgId": "..."
        }
        """
        msg_type = payload.get("msgtype", "")
        if msg_type != "text":
            logger.debug("Ignoring DingTalk message type: %s", msg_type)
            return None

        text = payload.get("text", {}).get("content", "").strip()
        if not text:
            return None

        conversation_id = payload.get("conversationId", "")
        conversation_type = payload.get("conversationType", "2")

        return IMInboundMessage(
            platform="dingtalk",
            chat_id=conversation_id,
            sender_id=payload.get("senderId", ""),
            sender_name=payload.get("senderNick", "unknown"),
            content=text,
            message_id=payload.get("msgId", ""),
            timestamp=datetime.now(timezone.utc),
            is_group=(conversation_type == "2"),
            app_name=self.app_name,
        )
