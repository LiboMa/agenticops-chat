"""IM Gateway — abstract base + unified inbound message model."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class IMInboundMessage:
    """Unified inbound message format from any IM platform."""

    platform: str           # "feishu" | "dingtalk" | "wecom"
    chat_id: str            # Group chat ID
    sender_id: str          # Sender user ID
    sender_name: str        # Sender display name
    content: str            # Message text content
    message_id: str         # Platform message ID (for dedup)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_group: bool = True   # Group chat vs direct message
    app_name: str = "default"  # Corresponding YAML app name


class IMGateway(ABC):
    """Abstract IM platform gateway — webhook callback handling."""

    platform: str = ""

    @abstractmethod
    def verify_callback(self, request_body: bytes, headers: Dict[str, str]) -> bool:
        """Verify the webhook callback signature.

        Returns True if the signature is valid.
        """

    @abstractmethod
    def parse_message(self, payload: Dict[str, Any]) -> Optional[IMInboundMessage]:
        """Parse the webhook payload into a unified message.

        Returns None if the payload is not a user message (e.g. system event).
        """
