"""Slack Socket Mode client — receives IM messages, dispatches to Agent.

Uses slack_sdk's SocketModeClient for outbound WebSocket (no public URL needed).
The bot connects to Slack's servers via WebSocket and receives events in real-time.
"""

import json
import logging
import logging.handlers
import re
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Optional

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from agenticops.config import PROJECT_ROOT, settings
from agenticops.im.session_manager import IMChatSessionManager
from agenticops.notify.im_config import get_slack_app

logger = logging.getLogger(__name__)


def _setup_file_logging() -> None:
    """Configure file logging for the Slack WS service and related modules."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "slack_ws.log"

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s [%(trace_id)s] %(message)s"
    ))

    # Add trace_id filter
    from agenticops.web.app import TraceIdFilter
    handler.addFilter(TraceIdFilter())

    for name in (
        "agenticops.im",
        "agenticops.integrations",
        "agenticops.services.rca_service",
        "agenticops.services.pipeline_service",
        "agenticops.notify",
    ):
        logging.getLogger(name).addHandler(handler)

    logging.getLogger().addHandler(handler)
    logger.info("File logging -> %s", log_file)


# Thread pool for agent invocations (avoid blocking Socket Mode event loop)
_AGENT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slack-agent")

# @mention pattern in Slack message text: <@U12345ABC>
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>\s*")


class SlackWSService:
    """Slack Socket Mode service.

    Connects to Slack via outbound WebSocket (no public URL / callback needed).
    Receives message events and dispatches to per-chat Agents.
    Replies via Web API.
    """

    def __init__(self, app_name: str = "default"):
        self._app_name = app_name
        self._app_config = get_slack_app(app_name)
        if not self._app_config:
            raise ValueError(f"Slack app '{app_name}' not found in im-apps.yaml")
        if not self._app_config.app_token:
            raise ValueError(
                f"Slack app '{app_name}' missing app_token (xapp-...) — "
                "required for Socket Mode"
            )

        self._im_sessions = IMChatSessionManager()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._bot_user_id: str = ""
        self._respond_to: str = self._app_config.respond_to or "mentions_only"
        # Per-chat lock: Strands Agent doesn't support concurrent invocations,
        # so we serialize messages for the same chat_id.
        self._chat_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

        # Web API client for sending replies
        self._web_client = WebClient(token=self._app_config.bot_token)

        # Socket Mode client
        self._socket_client = SocketModeClient(
            app_token=self._app_config.app_token,
            web_client=self._web_client,
        )
        self._socket_client.socket_mode_request_listeners.append(self._on_event)

    # ------------------------------------------------------------------
    # Event handler (called in Socket Mode client's thread)
    # ------------------------------------------------------------------

    def _on_event(self, client: SocketModeClient, req: SocketModeRequest) -> None:
        """Handle incoming Socket Mode event."""
        # Ack immediately (Slack requires ack within 3 seconds)
        client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        if event.get("type") != "message":
            return

        # Skip message subtypes (edits, joins, etc.)
        if event.get("subtype"):
            return

        # Skip our own messages by user ID
        user = event.get("user", "")
        if self._bot_user_id and user == self._bot_user_id:
            return

        text = (event.get("text") or "").strip()
        if not text:
            return

        # Check for @mention BEFORE bot filtering — other bots (e.g. alert-bot)
        # may @mention us to trigger RCA processing.
        has_mention = bool(re.search(rf"<@{self._bot_user_id}>", text)) if self._bot_user_id else False

        # Skip bot messages UNLESS they @mention us
        if event.get("bot_id") and not has_mention:
            return

        channel = event.get("channel", "")

        if self._respond_to == "mentions_only":
            # Check if this is an alert channel (always respond in alert channels)
            is_alert = False
            try:
                from agenticops.notify.im_config import find_channel_by_chat
                ch = find_channel_by_chat("slack", channel)
                if ch and ch.role == "alert":
                    is_alert = True
            except Exception:
                pass

            if not has_mention and not is_alert:
                return

        # Strip @mentions from text
        text = _MENTION_RE.sub("", text).strip()
        if not text:
            return

        message_id = event.get("ts", "")

        logger.info(
            "Slack WS message: channel=%s user=%s text=%s",
            channel, user, text[:80],
        )

        # Dispatch to thread pool (don't block Socket Mode event loop)
        _AGENT_POOL.submit(
            self._process_and_reply,
            channel,
            text,
            message_id,
            user,
            has_mention,
        )

    # ------------------------------------------------------------------
    # Channel history context
    # ------------------------------------------------------------------

    def _fetch_channel_context(
        self, channel: str, current_ts: str, limit: int = 15,
    ) -> str:
        """Fetch recent channel messages as context for the Agent.

        Returns formatted history block, or empty string on failure.
        Includes bot messages (these are the alerts we want the Agent to see).
        Excludes the current message itself.
        """
        try:
            resp = self._web_client.conversations_history(
                channel=channel,
                limit=limit + 1,  # +1 in case current msg is included
            )
            if not resp.get("ok"):
                logger.warning(
                    "conversations.history failed: %s", resp.get("error")
                )
                return ""

            messages = resp.get("messages", [])
            if not messages:
                return ""

            lines = []
            for msg in reversed(messages):  # oldest first
                ts = msg.get("ts", "")
                if ts == current_ts:
                    continue  # skip the triggering @mention itself

                user = msg.get("user") or msg.get("bot_id") or "unknown"
                # Mark bot messages clearly
                if msg.get("bot_id"):
                    username = msg.get("username") or msg.get("bot_id", "bot")
                    prefix = f"[BOT:{username}]"
                else:
                    prefix = f"[USER:{user}]"

                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                lines.append(f"{prefix} {text}")

            if not lines:
                return ""

            history_block = "\n".join(lines)
            return (
                f"\n<channel_history recent_messages=\"{len(lines)}\">\n"
                f"{history_block}\n"
                f"</channel_history>\n\n"
            )
        except Exception:
            logger.debug("Failed to fetch channel history", exc_info=True)
            return ""

    # ------------------------------------------------------------------
    # Agent processing + reply (runs in thread pool)
    # ------------------------------------------------------------------

    def _process_and_reply(
        self, chat_id: str, text: str, message_id: str, sender_id: str,
        was_mentioned: bool = False,
    ) -> None:
        """Process message through Agent and reply (serialized per chat_id)."""
        lock = self._chat_locks[chat_id]
        if not lock.acquire(timeout=120):
            logger.warning("Chat %s busy, dropping message: %s", chat_id, text[:50])
            self._send_reply(chat_id, "Message processing is busy, please try again shortly.")
            return
        try:
            # Intercept /send_to command before agent dispatch
            if text.strip().lower().startswith(("/send_to ", "/sendto ")):
                from agenticops.chat.send_to import execute_send_to
                send_result = execute_send_to(text.strip())
                response_text = send_result.message
            else:
                # All messages go through Main Agent.
                # For alert channels, only wrap with alert context when
                # the bot was @mentioned — normal conversation stays normal.
                agent = self._im_sessions.get_or_create(
                    "slack", chat_id, self._app_name
                )
                if was_mentioned:
                    # Fetch recent channel history as context — lets the Agent
                    # see Alertbot messages and prior conversation, not just
                    # the current @mention text.
                    history_ctx = self._fetch_channel_context(
                        chat_id, message_id,
                    )
                    enriched_text = history_ctx + text
                    from agenticops.im.feishu_ws import _build_agent_input
                    agent_input = _build_agent_input(
                        enriched_text, "slack", chat_id, sender_id
                    )
                else:
                    agent_input = text
                logger.info(
                    ">>> Agent dispatch: chat_id=%s is_alert_ctx=%s input_len=%d",
                    chat_id,
                    agent_input != text,
                    len(agent_input),
                )
                logger.debug(">>> Agent input (first 500): %s", agent_input[:500])
                # Set IM origin + trace_id context
                from agenticops.config import set_im_origin, generate_trace_id, set_trace_id
                _im_token = set_im_origin({"platform": "slack", "chat_id": chat_id})
                _trace_token = set_trace_id(generate_trace_id())
                result = agent(agent_input)
                set_im_origin(None)  # clear after agent completes
                set_trace_id(None)
                response_text = str(result)
                logger.info(
                    ">>> Agent response (first 300): %s", response_text[:300]
                )

            # Persist conversation to DB
            self._persist_messages(chat_id, sender_id, text, response_text)

            # Reply via Web API
            self._send_reply(chat_id, response_text)
        except Exception:
            logger.exception("Error processing Slack message for chat %s", chat_id)
            self._send_reply(chat_id, "Sorry, an error occurred while processing your message. Please try again.")
        finally:
            lock.release()

    def _send_reply(self, channel: str, text: str) -> None:
        """Send text reply to Slack channel via Web API."""
        try:
            response = self._web_client.chat_postMessage(
                channel=channel,
                text=text,
            )
            if not response.get("ok"):
                logger.error(
                    "Failed to send Slack reply: %s",
                    response.get("error", "unknown"),
                )
            else:
                logger.info("Slack reply sent to channel %s", channel)
        except Exception:
            logger.exception("Error sending Slack reply to channel %s", channel)

    # ------------------------------------------------------------------
    # DB persistence (best-effort)
    # ------------------------------------------------------------------

    def _persist_messages(
        self, chat_id: str, sender_id: str, user_text: str, bot_text: str
    ) -> None:
        """Persist IM messages to ChatSession/ChatMessage tables."""
        try:
            from agenticops.models import ChatSession, ChatMessage, get_db_session

            with get_db_session() as db:
                session = (
                    db.query(ChatSession)
                    .filter_by(im_platform="slack", im_chat_id=chat_id)
                    .first()
                )
                if not session:
                    session = ChatSession(
                        session_id=str(uuid.uuid4()),
                        name=f"Slack {chat_id[:12]}",
                        im_platform="slack",
                        im_chat_id=chat_id,
                    )
                    db.add(session)
                    db.flush()

                db.add(
                    ChatMessage(
                        session_id=session.id,
                        role="user",
                        content=user_text,
                    )
                )
                db.add(
                    ChatMessage(
                        session_id=session.id,
                        role="assistant",
                        content=bot_text,
                    )
                )
                db.commit()
                session.last_activity_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.debug("Failed to persist Slack IM messages", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start Socket Mode client in a daemon thread."""
        if self._started:
            logger.warning("Slack WS service already started")
            return

        _setup_file_logging()

        # Resolve bot user ID for self-message filtering
        try:
            auth_response = self._web_client.auth_test()
            self._bot_user_id = auth_response.get("user_id", "")
            logger.info("Slack bot user ID: %s", self._bot_user_id)
        except Exception:
            logger.warning("Could not resolve Slack bot user ID", exc_info=True)

        self._im_sessions.start_cleanup()
        self._thread = threading.Thread(
            target=self._run_ws,
            name="slack-ws",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        logger.info("Slack Socket Mode service started (app: %s)", self._app_name)

    def _run_ws(self) -> None:
        """Run Socket Mode client (blocking — runs in daemon thread)."""
        try:
            self._socket_client.connect()
            # Keep the thread alive
            import time
            while self._started:
                time.sleep(1)
        except Exception:
            logger.exception("Slack Socket Mode client exited with error")

    def stop(self) -> None:
        """Stop the service."""
        self._started = False
        try:
            self._socket_client.disconnect()
        except Exception:
            pass
        self._im_sessions.stop_cleanup()
        logger.info("Slack Socket Mode service stopped")


# ======================================================================
# Module-level singleton
# ======================================================================

_slack_ws_service: Optional[SlackWSService] = None


def start_slack_ws(app_name: str = "default") -> Optional[SlackWSService]:
    """Start the Slack Socket Mode service (singleton)."""
    global _slack_ws_service
    if _slack_ws_service is not None:
        return _slack_ws_service

    try:
        _slack_ws_service = SlackWSService(app_name=app_name)
        _slack_ws_service.start()
        return _slack_ws_service
    except Exception:
        logger.exception("Failed to start Slack Socket Mode service")
        return None


def stop_slack_ws() -> None:
    """Stop the Slack Socket Mode service."""
    global _slack_ws_service
    if _slack_ws_service:
        _slack_ws_service.stop()
        _slack_ws_service = None


# ======================================================================
# Standalone runner: python -m agenticops.im.slack_ws
# ======================================================================

if __name__ == "__main__":
    import signal
    import sys
    import time as _time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    svc = start_slack_ws()
    if not svc:
        sys.exit(1)

    print("Slack Socket Mode bot running. Press Ctrl+C to stop.")

    def _sig_handler(_sig, _frame):
        print("\nShutting down...")
        stop_slack_ws()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    while True:
        _time.sleep(1)
