"""Chat session manager — maintains per-session agent instances."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List

from strands import Agent

from agenticops.agents.main_agent import create_main_agent
from agenticops.config import settings

logger = logging.getLogger(__name__)

# Max characters per message before truncation
_MAX_MSG_CHARS = 4000


def _load_history_messages(session_id: str, max_turns: int) -> List[dict]:
    """Load recent messages from DB and convert to Strands Message format.

    Args:
        session_id: The string session UUID (ChatSession.session_id).
        max_turns: Number of conversation turns to load (each turn = user + assistant).

    Returns:
        List of Strands-compatible message dicts with role/content keys.
        Messages are in chronological order with strict user/assistant alternation.
    """
    from agenticops.models import ChatMessage, ChatSession, get_db_session

    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            return []

        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == row.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_turns * 2)
            .all()
        )

    if not rows:
        return []

    # Reverse to chronological order
    rows.reverse()

    # Convert to Strands message format
    raw_messages: List[dict] = []
    for msg in rows:
        content = msg.content or ""
        if not content.strip():
            continue

        # Truncate long messages
        if len(content) > _MAX_MSG_CHARS:
            content = content[:_MAX_MSG_CHARS] + "\n... (truncated)"

        # For assistant messages with tool_calls, add a prefix hint
        if msg.role == "assistant" and msg.tool_calls:
            try:
                tool_names = []
                calls = msg.tool_calls if isinstance(msg.tool_calls, list) else []
                for tc in calls:
                    name = tc.get("name") or tc.get("tool_name", "unknown")
                    tool_names.append(name)
                if tool_names:
                    content = f"[Used tools: {', '.join(tool_names)}]\n{content}"
            except (TypeError, AttributeError):
                pass

        raw_messages.append({
            "role": msg.role,
            "content": [{"text": content}],
        })

    if not raw_messages:
        return []

    # Fix role alternation: merge consecutive same-role messages
    merged: List[dict] = [raw_messages[0]]
    for m in raw_messages[1:]:
        if m["role"] == merged[-1]["role"]:
            prev_text = merged[-1]["content"][0]["text"]
            cur_text = m["content"][0]["text"]
            merged[-1]["content"][0]["text"] = prev_text + "\n\n" + cur_text
        else:
            merged.append(m)

    # Ensure first message is from user (Bedrock requires user-first)
    if merged[0]["role"] == "assistant":
        merged.insert(0, {
            "role": "user",
            "content": [{"text": "(continuing previous conversation)"}],
        })

    return merged


class ChatSessionManager:
    """Manages per-session agent instances with lazy creation and TTL cleanup.

    Uses per-session locks so creating/restoring one session never blocks
    other sessions from being served.
    """

    def __init__(self, ttl_minutes: int = 30):
        self._agents: Dict[str, Agent] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._lock = threading.Lock()  # guards _agents, _last_activity, _session_locks
        self._session_locks: Dict[str, threading.Lock] = {}
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
                self._session_locks.pop(sid, None)

    def get_or_create(self, session_id: str) -> Agent:
        # Fast path — agent already cached, no slow work
        with self._lock:
            if session_id in self._agents:
                self._last_activity[session_id] = datetime.utcnow()
                return self._agents[session_id]
            # Slow path needed — get or create a per-session lock
            sess_lock = self._session_locks.setdefault(session_id, threading.Lock())

        # Only this session is locked; other sessions proceed freely
        with sess_lock:
            # Double-check after acquiring per-session lock
            with self._lock:
                if session_id in self._agents:
                    self._last_activity[session_id] = datetime.utcnow()
                    return self._agents[session_id]

            # Expensive work — outside global lock
            logger.info("Creating agent for session %s", session_id)
            agent = create_main_agent()
            history = _load_history_messages(session_id, settings.session_history_depth)
            if history:
                agent.messages.extend(history)
                logger.info("Restored %d messages for session %s", len(history), session_id)

            with self._lock:
                self._agents[session_id] = agent
                self._last_activity[session_id] = datetime.utcnow()
                return agent

    def remove(self, session_id: str):
        with self._lock:
            self._agents.pop(session_id, None)
            self._last_activity.pop(session_id, None)
            self._session_locks.pop(session_id, None)
