"""Feishu (飞书) IM Gateway — Event Subscription v2."""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from agenticops.im.gateway import IMGateway, IMInboundMessage
from agenticops.notify.im_config import get_feishu_app
from agenticops.utils.timeutils import utc_now

logger = logging.getLogger(__name__)


class FeishuGateway(IMGateway):
    """Feishu Event Subscription gateway.

    Handles:
    - URL verification challenge (first-time callback registration)
    - im.message.receive_v1 events (text messages)
    - Signature verification via X-Lark-Signature header
    """

    platform = "feishu"

    def __init__(self, app_name: str = "default"):
        self.app_name = app_name
        self._app_config = get_feishu_app(app_name)

    def verify_callback(self, request_body: bytes, headers: Dict[str, str]) -> bool:
        """Verify Feishu Event Subscription signature.

        Feishu sends X-Lark-Signature = SHA256(timestamp + nonce + encrypt_key + body).
        If no encrypt_key is configured, skip verification (dev mode).
        """
        if not self._app_config or not self._app_config.encrypt_key:
            return True  # No encrypt_key = dev mode, skip verification

        signature = headers.get("x-lark-signature", "")
        timestamp = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")

        if not signature:
            return True  # Unsigned request — old API version, allow

        content = f"{timestamp}{nonce}{self._app_config.encrypt_key}"
        content_bytes = content.encode() + request_body
        expected = hashlib.sha256(content_bytes).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_message(self, payload: Dict[str, Any]) -> Optional[IMInboundMessage]:
        """Parse Feishu im.message.receive_v1 event into IMInboundMessage.

        Returns None for non-text messages or system events.
        """
        # URL verification challenge — handled separately in route
        if payload.get("type") == "url_verification":
            return None

        # Event v2 format
        header = payload.get("header", {})
        event = payload.get("event", {})
        event_type = header.get("event_type", "")

        if event_type != "im.message.receive_v1":
            logger.debug("Ignoring Feishu event type: %s", event_type)
            return None

        message = event.get("message", {})
        msg_type = message.get("message_type", "")
        if msg_type != "text":
            logger.debug("Ignoring Feishu message type: %s", msg_type)
            return None

        # Extract text content — Feishu wraps it in JSON
        raw_content = message.get("content", "{}")
        try:
            text = json.loads(raw_content).get("text", "")
        except (json.JSONDecodeError, AttributeError):
            text = raw_content

        if not text.strip():
            return None

        # Remove @bot mention prefix if present
        if text.startswith("@"):
            # Feishu format: "@_user_xxx text"
            parts = text.split(" ", 1)
            text = parts[1] if len(parts) > 1 else text

        sender = event.get("sender", {})
        sender_id_obj = sender.get("sender_id", {})

        chat_id = message.get("chat_id", "")
        chat_type = message.get("chat_type", "group")  # group or p2p

        return IMInboundMessage(
            platform="feishu",
            chat_id=chat_id,
            sender_id=sender_id_obj.get("user_id", sender_id_obj.get("open_id", "")),
            sender_name=sender.get("sender_id", {}).get("user_id", "unknown"),
            content=text.strip(),
            message_id=message.get("message_id", ""),
            timestamp=utc_now(),
            is_group=(chat_type == "group"),
            app_name=self.app_name,
        )

    @staticmethod
    def is_challenge(payload: Dict[str, Any]) -> bool:
        """Check if this is a URL verification challenge."""
        return payload.get("type") == "url_verification"

    @staticmethod
    def challenge_response(payload: Dict[str, Any]) -> Dict[str, str]:
        """Build the challenge response."""
        return {"challenge": payload.get("challenge", "")}
