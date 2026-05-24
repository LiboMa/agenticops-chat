"""Chat session manager — maintains per-session agent instances."""

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from strands import Agent

from agenticops.agents.main_agent import create_main_agent
from agenticops.config import settings
from agenticops.models import AgentMemoryFact

logger = logging.getLogger(__name__)

# Max characters per message before truncation
_MAX_MSG_CHARS = 4000


def _rebuild_tool_messages(tool_calls: list) -> list[dict]:
    """Rebuild DB tool_calls JSON into Strands SDK toolUse + toolResult message pairs.

    For each tool call entry, produces:
      1. An assistant message with a ``toolUse`` content block.
      2. A user message with a matching ``toolResult`` content block using
         placeholder text ``"(result from previous session)"``.

    Args:
        tool_calls: List of dicts from the DB ``ChatMessage.tool_calls`` JSON
                    column.  Each dict is expected to have at least ``name``
                    (or ``tool_name``) and ``input`` keys.

    Returns:
        Flat list of Strands-compatible message dicts (assistant/user pairs).
        Returns an empty list when *tool_calls* is not a non-empty list or
        when any entry fails to parse, so the caller can fall back to the
        text-prefix approach.
    """
    if not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return []

    try:
        messages: list[dict] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                logger.warning("_rebuild_tool_messages: non-dict entry in tool_calls, falling back")
                return []

            name = tc.get("name") or tc.get("tool_name")
            if not name:
                logger.warning("_rebuild_tool_messages: tool call missing name, falling back")
                return []

            tool_input = tc.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}

            tool_use_id = tc.get("toolUseId") or tc.get("tool_use_id") or str(uuid.uuid4())

            # Assistant message with toolUse
            messages.append({
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": tool_input,
                        }
                    }
                ],
            })

            # User message with toolResult
            messages.append({
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": "(result from previous session)"}],
                            "status": "success",
                        }
                    }
                ],
            })

        return messages
    except Exception:
        logger.warning("_rebuild_tool_messages: failed to parse tool_calls, falling back", exc_info=True)
        return []


def _load_history_messages(session_id: str, max_turns: int) -> List[dict]:
    """Load recent messages from DB and convert to Strands Message format.

    Also loads session summaries (if any) and prepends them as context-prefix
    user messages before the actual history messages.

    Args:
        session_id: The string session UUID (ChatSession.session_id).
        max_turns: Number of conversation turns to load (each turn = user + assistant).

    Returns:
        List of Strands-compatible message dicts with role/content keys.
        Messages are in chronological order with strict user/assistant alternation.
        Summaries appear before history messages.
    """
    from agenticops.models import ChatMessage, ChatSession, SessionSummary, get_db_session

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

        # Load session summaries ordered by creation time
        summary_rows = (
            db.query(SessionSummary)
            .filter(SessionSummary.session_id == row.id)
            .order_by(SessionSummary.created_at.asc())
            .all()
        )

        # Materialise summary texts while session is open
        summary_texts = [s.summary_text for s in summary_rows if s.summary_text]

        if not rows and not summary_texts:
            return []

        # Materialise attributes while session is open to avoid DetachedInstanceError
        row_data = [
            {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls}
            for msg in rows
        ] if rows else []

    # Reverse to chronological order
    row_data.reverse()

    # Convert to Strands message format
    raw_messages: List[dict] = []
    for msg in row_data:
        content = msg["content"]
        if not content.strip():
            continue

        # Truncate long messages
        if len(content) > _MAX_MSG_CHARS:
            content = content[:_MAX_MSG_CHARS] + "\n... (truncated)"

        # For assistant messages with tool_calls, try faithful reconstruction first
        if msg["role"] == "assistant" and msg["tool_calls"]:
            rebuilt = _rebuild_tool_messages(msg["tool_calls"])
            if rebuilt:
                # Faithful reconstruction succeeded — emit the text content
                # as a plain assistant message, then the toolUse/toolResult pairs
                raw_messages.append({
                    "role": msg["role"],
                    "content": [{"text": content}],
                })
                raw_messages.extend(rebuilt)
                continue

            # Fallback: _rebuild_tool_messages returned [] (parse failure)
            logger.warning(
                "Failed to rebuild tool messages for session %s, "
                "falling back to text prefix",
                session_id,
            )
            try:
                tool_names = []
                calls = msg["tool_calls"] if isinstance(msg["tool_calls"], list) else []
                for tc in calls:
                    name = tc.get("name") or tc.get("tool_name", "unknown")
                    tool_names.append(name)
                if tool_names:
                    content = f"[Used tools: {', '.join(tool_names)}]\n{content}"
            except (TypeError, AttributeError):
                pass

        raw_messages.append({
            "role": msg["role"],
            "content": [{"text": content}],
        })

    if not raw_messages and not summary_texts:
        return []

    # Build summary context-prefix messages
    summary_messages: List[dict] = []
    if summary_texts:
        combined_summary = "\n\n".join(summary_texts)
        summary_messages.append({
            "role": "user",
            "content": [{"text": f"[Previous conversation summary]\n{combined_summary}"}],
        })
        summary_messages.append({
            "role": "assistant",
            "content": [{"text": "Understood, I have the context from the previous conversation summary."}],
        })

    if not raw_messages:
        return summary_messages

    # Fix role alternation: merge consecutive same-role messages
    merged: List[dict] = [raw_messages[0]]
    for m in raw_messages[1:]:
        if m["role"] == merged[-1]["role"]:
            prev_content = merged[-1]["content"]
            cur_content = m["content"]
            # Only text-merge when both sides are simple text blocks
            if (
                len(prev_content) == 1
                and "text" in prev_content[0]
                and len(cur_content) == 1
                and "text" in cur_content[0]
            ):
                prev_content[0]["text"] += "\n\n" + cur_content[0]["text"]
            else:
                # Append content blocks (toolUse / toolResult / mixed)
                prev_content.extend(cur_content)
        else:
            merged.append(m)

    # Prepend summary messages before history messages
    result = summary_messages + merged

    # Ensure first message is from user (Bedrock requires user-first)
    if result[0]["role"] == "assistant":
        result.insert(0, {
            "role": "user",
            "content": [{"text": "(continuing previous conversation)"}],
        })

    return result


def _format_facts_for_prompt(facts: list[AgentMemoryFact]) -> str:
    """Format high-confidence facts into a system prompt section.

    Args:
        facts: List of AgentMemoryFact objects to format.

    Returns:
        Formatted string section, or empty string if no facts.
    """
    if not facts:
        return ""

    lines = ["[Cross-session memory - Known facts]"]
    for fact in facts:
        lines.append(
            f"- {fact.category}/{fact.key}: {fact.value} "
            f"(confidence: {fact.confidence_score:.2f})"
        )
    return "\n".join(lines)


def _load_raw_messages(session_id: str) -> list[dict]:
    """Load raw messages from DB for a given session UUID.

    Returns a list of Strands-format message dicts (role + content) suitable
    for passing to SummaryService / MemoryService.  Returns an empty list
    when the session does not exist or has no messages.

    Args:
        session_id: The ChatSession.session_id (UUID string).
    """
    from agenticops.models import ChatMessage, ChatSession, get_db_session

    try:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(
                ChatSession.session_id == session_id
            ).first()
            if not row:
                return []

            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == row.id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            if not rows:
                return []

            return [
                {"role": msg.role, "content": msg.content or ""}
                for msg in rows
            ]
    except Exception:
        logger.error(
            "Failed to load raw messages for session %s", session_id, exc_info=True
        )
        return []


def _trigger_memory_extraction(session_id: str) -> None:
    """Trigger memory extraction (facts + experiences) for a session.

    Loads the session's messages from DB and calls MemoryService to extract
    structured facts and vectorized experiences.  All failures are logged
    as errors but never propagated — the caller's normal flow is never blocked.

    Args:
        session_id: The ChatSession.session_id (UUID string).
    """
    messages = _load_raw_messages(session_id)
    if not messages:
        logger.info(
            "No messages to extract memory from for session %s", session_id
        )
        return

    from agenticops.web.memory_service import MemoryService

    svc = MemoryService()

    try:
        svc.extract_facts(session_id, messages)
        logger.info("Extracted facts for session %s", session_id)
    except Exception:
        logger.error(
            "Failed to extract facts for session %s", session_id, exc_info=True
        )

    try:
        svc.extract_experiences(session_id, messages)
        logger.info("Extracted experiences for session %s", session_id)
    except Exception:
        logger.error(
            "Failed to extract experiences for session %s",
            session_id,
            exc_info=True,
        )


def _trigger_summary_and_memory(session_id: str) -> None:
    """Trigger summary generation AND memory extraction for a session.

    Used during TTL cleanup to capture both the conversation summary and
    cross-session memories before the agent instance is discarded.

    Args:
        session_id: The ChatSession.session_id (UUID string).
    """
    messages = _load_raw_messages(session_id)
    if not messages:
        logger.info(
            "No messages for summary/memory extraction for session %s",
            session_id,
        )
        return

    # 1. Summary generation
    try:
        from agenticops.web.summary_service import SummaryService
        from agenticops.models import ChatSession, get_db_session

        # SummaryService.generate_summary expects the DB primary key (int)
        with get_db_session() as db:
            row = db.query(ChatSession).filter(
                ChatSession.session_id == session_id
            ).first()
            db_pk = row.id if row else None

        if db_pk is not None:
            SummaryService().generate_summary(messages, db_pk)
            logger.info("Generated summary for session %s", session_id)
    except Exception:
        logger.error(
            "Failed to generate summary for session %s",
            session_id,
            exc_info=True,
        )

    # 2. Memory extraction (facts + experiences)
    from agenticops.web.memory_service import MemoryService

    svc = MemoryService()

    try:
        svc.extract_facts(session_id, messages)
        logger.info("Extracted facts for session %s", session_id)
    except Exception:
        logger.error(
            "Failed to extract facts for session %s", session_id, exc_info=True
        )

    try:
        svc.extract_experiences(session_id, messages)
        logger.info("Extracted experiences for session %s", session_id)
    except Exception:
        logger.error(
            "Failed to extract experiences for session %s",
            session_id,
            exc_info=True,
        )


class ChatSessionManager:
    """Manages per-session agent instances with lazy creation and TTL cleanup.

    Uses per-session locks so creating/restoring one session never blocks
    other sessions from being served.
    """

    def __init__(self):
        self._agents: Dict[str, Agent] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._lock = threading.Lock()  # guards _agents, _last_activity, _session_locks
        self._session_locks: Dict[str, threading.Lock] = {}
        self._ttl = timedelta(minutes=settings.session_ttl_minutes)
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
        now = datetime.now(timezone.utc)
        with self._lock:
            stale = [sid for sid, ts in self._last_activity.items() if now - ts > self._ttl]
            for sid in stale:
                logger.info("Cleaning up stale agent for session %s", sid)
                self._agents.pop(sid, None)
                self._last_activity.pop(sid, None)
                self._session_locks.pop(sid, None)

        # Trigger summary + memory extraction outside the lock so we don't
        # block other sessions.  Failures are logged but never propagated.
        for sid in stale:
            try:
                _trigger_summary_and_memory(sid)
            except Exception:
                logger.error(
                    "Unexpected error during summary/memory extraction for stale session %s",
                    sid,
                    exc_info=True,
                )

    def get_or_create(self, session_id: str) -> Agent:
        # Fast path — agent already cached, no slow work
        with self._lock:
            if session_id in self._agents:
                self._last_activity[session_id] = datetime.now(timezone.utc)
                return self._agents[session_id]
            # Slow path needed — get or create a per-session lock
            sess_lock = self._session_locks.setdefault(session_id, threading.Lock())

        # Only this session is locked; other sessions proceed freely
        with sess_lock:
            # Double-check after acquiring per-session lock
            with self._lock:
                if session_id in self._agents:
                    self._last_activity[session_id] = datetime.now(timezone.utc)
                    return self._agents[session_id]

            # Expensive work — outside global lock
            logger.info("Creating agent for session %s", session_id)
            agent = create_main_agent()
            history = _load_history_messages(session_id, settings.session_history_depth)
            if history:
                agent.messages.extend(history)
                logger.info("Restored %d messages for session %s", len(history), session_id)

            # Inject cross-session memory (facts + experiences) into system prompt
            try:
                from agenticops.web.memory_service import MemoryService

                memory_context = MemoryService().build_memory_context(
                    session_id=session_id, initial_context=""
                )
                if memory_context:
                    agent.system_prompt = agent.system_prompt + "\n\n" + memory_context
                    logger.info(
                        "Injected memory context into system prompt for session %s",
                        session_id,
                    )
            except Exception:
                logger.warning(
                    "Failed to inject memory context for session %s, continuing without memory",
                    session_id,
                    exc_info=True,
                )

            with self._lock:
                self._agents[session_id] = agent
                self._last_activity[session_id] = datetime.now(timezone.utc)
                return agent

    def remove(self, session_id: str):
        with self._lock:
            self._agents.pop(session_id, None)
            self._last_activity.pop(session_id, None)
            self._session_locks.pop(session_id, None)
