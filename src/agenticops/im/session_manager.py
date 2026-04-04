"""IM Chat Session Manager — per-chat Agent instances with TTL cleanup."""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from strands import Agent

from agenticops.agents.main_agent import create_main_agent
from agenticops.notify.notifier import IMNotifier, FeishuNotifier, DingTalkNotifier, WeComNotifier, SlackIMNotifier

logger = logging.getLogger(__name__)

# Platform → Notifier class mapping
_NOTIFIER_MAP = {
    "feishu": FeishuNotifier,
    "dingtalk": DingTalkNotifier,
    "wecom": WeComNotifier,
    "slack": SlackIMNotifier,
}


class IMChatSessionManager:
    """Per IM chat_id agent session manager with TTL cleanup.

    Each unique (platform, chat_id) gets its own Agent instance and a
    corresponding Notifier for sending replies back to the IM chat.
    """

    def __init__(self, ttl_minutes: int = 60):
        self._agents: Dict[str, Agent] = {}
        self._notifiers: Dict[str, IMNotifier] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._ttl = timedelta(minutes=ttl_minutes)
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown = False

    def start_cleanup(self) -> None:
        if self._cleanup_thread is None:
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        self._shutdown = True
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)

    def _cleanup_loop(self) -> None:
        while not self._shutdown:
            time.sleep(60)
            self._remove_stale()

    def _remove_stale(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            stale = [k for k, ts in self._last_activity.items() if now - ts > self._ttl]
            for k in stale:
                logger.info("Cleaning up stale IM agent for %s", k)
                self._agents.pop(k, None)
                self._notifiers.pop(k, None)
                self._last_activity.pop(k, None)

    def _key(self, platform: str, chat_id: str) -> str:
        return f"{platform}:{chat_id}"

    def get_or_create(self, platform: str, chat_id: str, app_name: str = "default") -> Agent:
        """Get or create an Agent for the given IM chat."""
        key = self._key(platform, chat_id)
        with self._lock:
            if key not in self._agents:
                logger.info("Creating IM agent for %s", key)
                self._agents[key] = create_main_agent()
            self._last_activity[key] = datetime.now(timezone.utc)
            return self._agents[key]

    def get_notifier(self, platform: str, chat_id: str, app_name: str = "default") -> Optional[IMNotifier]:
        """Get or create a Notifier for sending replies to the IM chat."""
        key = self._key(platform, chat_id)
        with self._lock:
            if key not in self._notifiers:
                notifier_cls = _NOTIFIER_MAP.get(platform)
                if not notifier_cls:
                    logger.error("Unknown IM platform: %s", platform)
                    return None
                config = {"app_name": app_name, "chat_id": chat_id}
                self._notifiers[key] = notifier_cls(config)
            return self._notifiers[key]

    def remove(self, platform: str, chat_id: str) -> None:
        key = self._key(platform, chat_id)
        with self._lock:
            self._agents.pop(key, None)
            self._notifiers.pop(key, None)
            self._last_activity.pop(key, None)
