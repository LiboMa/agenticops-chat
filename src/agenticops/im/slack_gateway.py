"""Slack IM Gateway — HTTP Events API webhook handler.

Handles Slack's URL verification challenge and event_callback payloads.
Signature verification uses HMAC-SHA256 of v0:timestamp:body.
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional

from agenticops.im.gateway import IMGateway, IMInboundMessage
from agenticops.notify.im_config import get_slack_app

logger = logging.getLogger(__name__)


class SlackGateway(IMGateway):
    """Slack Events API gateway for webhook-based message handling."""

    platform = "slack"

    def __init__(self, app_name: str = "default"):
        self._app_name = app_name
        self._app_config = get_slack_app(app_name)

    def verify_callback(self, request_body: bytes, headers: Dict[str, str]) -> bool:
        """Verify Slack request signature (HMAC-SHA256).

        Slack sends:
          X-Slack-Signature: v0=<hex_digest>
          X-Slack-Request-Timestamp: <unix_ts>

        Signature base string: v0:{timestamp}:{body}
        """
        if not self._app_config or not self._app_config.signing_secret:
            logger.warning("Slack signing_secret not configured — skipping verification")
            return True

        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")

        if not timestamp or not signature:
            return False

        # Replay protection: reject requests older than 5 minutes
        try:
            if abs(time.time() - int(timestamp)) > 300:
                logger.warning("Slack request timestamp too old: %s", timestamp)
                return False
        except ValueError:
            return False

        sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
        computed = "v0=" + hmac.new(
            self._app_config.signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, signature)

    def parse_message(self, payload: Dict[str, Any]) -> Optional[IMInboundMessage]:
        """Parse a Slack event_callback into IMInboundMessage.

        Returns None for non-message events, bot messages, or subtypes.
        """
        event = payload.get("event", {})

        # Only handle plain messages (no subtype = user message)
        if event.get("type") != "message" or event.get("subtype"):
            return None

        # Skip bot messages
        if event.get("bot_id"):
            return None

        text = (event.get("text") or "").strip()
        if not text:
            return None

        # Strip @mentions: <@U12345> format
        import re
        text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
        if not text:
            return None

        channel = event.get("channel", "")
        user = event.get("user", "")
        ts = event.get("ts", "")

        return IMInboundMessage(
            platform="slack",
            chat_id=channel,
            sender_id=user,
            sender_name=user,  # Slack user ID; display name requires API call
            content=text,
            message_id=ts,
            app_name=self._app_name,
        )

    @staticmethod
    def is_challenge(payload: Dict[str, Any]) -> bool:
        """Check if this is a Slack URL verification challenge."""
        return payload.get("type") == "url_verification"

    @staticmethod
    def challenge_response(payload: Dict[str, Any]) -> Dict[str, str]:
        """Return the challenge response."""
        return {"challenge": payload.get("challenge", "")}
