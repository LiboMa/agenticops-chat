"""Chat session manager — maintains per-session agent instances."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict

from strands import Agent

from agenticops.agents.main_agent import create_main_agent

logger = logging.getLogger(__name__)


class ChatSessionManager:
    """Manages per-session agent instances with lazy creation and TTL cleanup."""

    def __init__(self, ttl_minutes: int = 30):
        self._agents: Dict[str, Agent] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._ttl = timedelta(minutes=ttl_minutes)
        self._cleanup_thread: threading.Thread | None = None
        self._shutdown = False

    def start_cleanup(self):
        if self._cleanup_thread is None:
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self._cleanup_thread.start()

    def stop_cleanup(self):
        self._shutdown = True
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)

    def _cleanup_loop(self):
        while not self._shutdown:
            time.sleep(60)
            self._remove_stale()

    def _remove_stale(self):
        now = datetime.utcnow()
        with self._lock:
            stale = [sid for sid, ts in self._last_activity.items() if now - ts > self._ttl]
            for sid in stale:
                logger.info("Cleaning up stale agent for session %s", sid)
                self._agents.pop(sid, None)
                self._last_activity.pop(sid, None)

    def get_or_create(self, session_id: str) -> Agent:
        with self._lock:
            if session_id not in self._agents:
                logger.info("Creating agent for session %s", session_id)
                self._agents[session_id] = create_main_agent()
            self._last_activity[session_id] = datetime.utcnow()
            return self._agents[session_id]

    def remove(self, session_id: str):
        with self._lock:
            self._agents.pop(session_id, None)
            self._last_activity.pop(session_id, None)
