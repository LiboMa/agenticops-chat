"""Feishu WebSocket long-connection client — receives IM messages, dispatches to Agent.

Uses lark-oapi SDK's WebSocket mode (outbound connection, no public URL needed).
The bot connects to Feishu's servers via WebSocket and receives events in real-time.
"""

import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)
from lark_oapi.ws import Client as WSClient

from agenticops.im.session_manager import IMChatSessionManager
from agenticops.notify.im_config import get_feishu_app

logger = logging.getLogger(__name__)

# Thread pool for agent invocations (avoid blocking WS event loop)
_AGENT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="feishu-agent")

# @mention placeholder pattern in Feishu message text
_MENTION_RE = re.compile(r"@_user_\d+\s*")


class FeishuWSService:
    """Feishu WebSocket long-connection service.

    Connects to Feishu via outbound WebSocket (no public URL / callback needed).
    Receives im.message.receive_v1 events and dispatches to per-chat Agents.
    Replies via REST API.
    """

    def __init__(self, app_name: str = "default"):
        self._app_name = app_name
        self._app_config = get_feishu_app(app_name)
        if not self._app_config:
            raise ValueError(f"Feishu app '{app_name}' not found in im-apps.yaml")

        self._im_sessions = IMChatSessionManager()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        # Per-chat lock: Strands Agent doesn't support concurrent invocations,
        # so we serialize messages for the same chat_id.
        self._chat_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

        # Build event dispatcher (handles decryption + signature verification)
        handler = (
            lark.EventDispatcherHandler.builder(
                self._app_config.encrypt_key or "",
                self._app_config.verification_token or "",
            )
            .register_p2_im_message_receive_v1(self._on_message_receive)
            .build()
        )

        # WebSocket client (outbound, auto-reconnect)
        self._ws_client = WSClient(
            app_id=self._app_config.app_id,
            app_secret=self._app_config.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
            auto_reconnect=True,
        )

        # REST client for sending replies
        self._rest_client = (
            lark.Client.builder()
            .app_id(self._app_config.app_id)
            .app_secret(self._app_config.app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    # ------------------------------------------------------------------
    # Event handler (called in WS client's asyncio loop)
    # ------------------------------------------------------------------

    def _on_message_receive(self, data: P2ImMessageReceiveV1) -> None:
        """Handle incoming message event from WebSocket."""
        try:
            event = data.event
            if not event or not event.message:
                return

            msg = event.message
            sender = event.sender

            # Only handle text messages
            if msg.message_type != "text":
                logger.debug("Ignoring Feishu message type: %s", msg.message_type)
                return

            # Parse content JSON: {"text": "@_user_1 hello"}
            try:
                content_obj = json.loads(msg.content)
                text = content_obj.get("text", "").strip()
            except (json.JSONDecodeError, TypeError):
                text = ""

            if not text:
                return

            # Strip @mentions
            text = _MENTION_RE.sub("", text).strip()
            if not text:
                return

            chat_id = msg.chat_id or ""
            sender_id = ""
            if sender and sender.sender_id:
                sender_id = (
                    sender.sender_id.open_id
                    or sender.sender_id.user_id
                    or ""
                )

            logger.info(
                "Feishu WS message: chat_id=%s sender=%s text=%s",
                chat_id,
                sender_id,
                text[:80],
            )

            # Dispatch to thread pool (don't block WS event loop)
            _AGENT_POOL.submit(
                self._process_and_reply,
                chat_id,
                text,
                msg.message_id or "",
                sender_id,
            )
        except Exception:
            logger.exception("Error handling Feishu WS message")

    # ------------------------------------------------------------------
    # Agent processing + reply (runs in thread pool)
    # ------------------------------------------------------------------

    def _process_and_reply(
        self, chat_id: str, text: str, message_id: str, sender_id: str
    ) -> None:
        """Process message through Agent and reply (serialized per chat_id)."""
        lock = self._chat_locks[chat_id]
        if not lock.acquire(timeout=120):
            logger.warning("Chat %s busy, dropping message: %s", chat_id, text[:50])
            self._send_reply(chat_id, "消息处理中，请稍后再试。")
            return
        try:
            # Intercept /send_to command before agent dispatch
            if text.strip().lower().startswith(("/send_to ", "/sendto ")):
                from agenticops.chat.send_to import execute_send_to
                send_result = execute_send_to(text.strip())
                response_text = send_result.message
            else:
                agent = self._im_sessions.get_or_create(
                    "feishu", chat_id, self._app_name
                )
                result = agent(text)
                response_text = str(result)

            # Persist conversation to DB
            self._persist_messages(chat_id, sender_id, text, response_text)

            # Reply via REST API
            self._send_reply(chat_id, response_text)
        except Exception:
            logger.exception("Error processing Feishu message for chat %s", chat_id)
            self._send_reply(chat_id, "抱歉，处理消息时出错，请稍后重试。")
        finally:
            lock.release()

    def _send_reply(self, chat_id: str, text: str) -> None:
        """Send text reply to Feishu chat via REST API."""
        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()
                )
                .build()
            )

            response = self._rest_client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    "Failed to send Feishu reply: code=%s msg=%s",
                    response.code,
                    response.msg,
                )
            else:
                logger.info("Feishu reply sent to chat %s", chat_id)
        except Exception:
            logger.exception("Error sending Feishu reply to chat %s", chat_id)

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
                # Find or create session for this IM chat
                session = (
                    db.query(ChatSession)
                    .filter_by(im_platform="feishu", im_chat_id=chat_id)
                    .first()
                )
                if not session:
                    session = ChatSession(
                        session_id=str(uuid.uuid4()),
                        name=f"Feishu {chat_id[:12]}",
                        im_platform="feishu",
                        im_chat_id=chat_id,
                    )
                    db.add(session)
                    db.flush()

                # User message
                db.add(
                    ChatMessage(
                        session_id=session.id,
                        role="user",
                        content=user_text,
                    )
                )
                # Bot reply
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
            logger.debug("Failed to persist Feishu IM messages", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start WebSocket client in a daemon thread."""
        if self._started:
            logger.warning("Feishu WS service already started")
            return

        self._im_sessions.start_cleanup()
        self._thread = threading.Thread(
            target=self._run_ws,
            name="feishu-ws",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        logger.info("Feishu WebSocket service started (app: %s)", self._app_name)

    def _run_ws(self) -> None:
        """Run WS client (blocking — runs in daemon thread)."""
        try:
            self._ws_client.start()
        except Exception:
            logger.exception("Feishu WebSocket client exited with error")

    def stop(self) -> None:
        """Stop the service."""
        self._im_sessions.stop_cleanup()
        self._started = False
        logger.info("Feishu WebSocket service stopped")


# ======================================================================
# Module-level singleton
# ======================================================================

_feishu_ws_service: Optional[FeishuWSService] = None


def start_feishu_ws(app_name: str = "default") -> Optional[FeishuWSService]:
    """Start the Feishu WebSocket service (singleton)."""
    global _feishu_ws_service
    if _feishu_ws_service is not None:
        return _feishu_ws_service

    try:
        _feishu_ws_service = FeishuWSService(app_name=app_name)
        _feishu_ws_service.start()
        return _feishu_ws_service
    except Exception:
        logger.exception("Failed to start Feishu WebSocket service")
        return None


def stop_feishu_ws() -> None:
    """Stop the Feishu WebSocket service."""
    global _feishu_ws_service
    if _feishu_ws_service:
        _feishu_ws_service.stop()
        _feishu_ws_service = None


# ======================================================================
# Standalone runner: python -m agenticops.im.feishu_ws
# ======================================================================

if __name__ == "__main__":
    import signal
    import sys
    import time as _time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    svc = start_feishu_ws()
    if not svc:
        sys.exit(1)

    print("Feishu WebSocket bot running. Press Ctrl+C to stop.")

    def _sig_handler(_sig, _frame):
        print("\nShutting down...")
        stop_feishu_ws()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    while True:
        _time.sleep(1)
