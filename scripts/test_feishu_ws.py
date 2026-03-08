#!/usr/bin/env python3
"""Feishu WebSocket diagnostic — test inbound message receiving.

Usage:
    uv run python scripts/test_feishu_ws.py

What it checks:
1. im-apps.yaml is loaded and app credentials exist
2. channels.yaml is loaded with role field
3. lark-oapi WSClient can connect
4. Listens for 60 seconds and prints any received messages

If you see "Feishu WebSocket connected" but no messages arrive when you
send in the Feishu group, check:
- Bot is added to the group
- Bot has "im:message" permission scope in Feishu Open Platform
- Event subscription type is "WebSocket" (not HTTP callback)
- Event "im.message.receive_v1" is subscribed
"""

import json
import logging
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("feishu-diag")

# Step 1: Check im-apps.yaml
print("\n" + "=" * 60)
print("STEP 1: Check im-apps.yaml")
print("=" * 60)

from agenticops.notify.im_config import get_feishu_app

app = get_feishu_app("default")
if not app:
    print("FAIL: Feishu app 'default' not found in im-apps.yaml")
    print("      Check config/im-apps.yaml has feishu.default.app_id")
    sys.exit(1)

print(f"  app_id:             {app.app_id[:8]}...{app.app_id[-4:]}")
print(f"  app_secret:         {'*' * 8}...{app.app_secret[-4:]}")
print(f"  encrypt_key:        {app.encrypt_key or '(empty)'}")
print(f"  verification_token: {app.verification_token[:8]}..." if app.verification_token else "  verification_token: (empty)")
print("  OK: App credentials loaded")

# Step 2: Check channels.yaml
print("\n" + "=" * 60)
print("STEP 2: Check channels.yaml")
print("=" * 60)

from agenticops.notify.im_config import load_channels

channels = load_channels()
feishu_channels = [c for c in channels if c.channel_type == "feishu"]
if not feishu_channels:
    print("  WARN: No Feishu channels in channels.yaml")
else:
    for ch in feishu_channels:
        print(f"  {ch.name}: role={ch.role}, chat_id={ch.config.get('chat_id', '?')[:20]}...")
        if ch.alert_senders:
            print(f"    alert_senders: {ch.alert_senders}")

# Step 3: Test WebSocket connection
print("\n" + "=" * 60)
print("STEP 3: WebSocket connection test")
print("=" * 60)

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    from lark_oapi.ws import Client as WSClient
except ImportError as e:
    print(f"FAIL: lark-oapi not installed: {e}")
    print("      pip install lark-oapi")
    sys.exit(1)

received_count = 0


def on_message(data: P2ImMessageReceiveV1) -> None:
    global received_count
    received_count += 1
    try:
        event = data.event
        msg = event.message if event else None
        sender = event.sender if event else None

        chat_id = msg.chat_id if msg else "?"
        msg_type = msg.message_type if msg else "?"
        content = msg.content if msg else ""
        sender_id = ""
        if sender and sender.sender_id:
            sender_id = sender.sender_id.open_id or sender.sender_id.user_id or ""

        print(f"\n  >>> MESSAGE RECEIVED #{received_count}!")
        print(f"      chat_id:  {chat_id}")
        print(f"      sender:   {sender_id}")
        print(f"      type:     {msg_type}")
        print(f"      content:  {content[:200]}")

        # Check alert routing
        from agenticops.im.alert_pipeline import should_handle_as_alert
        if msg_type == "text":
            try:
                text = json.loads(content).get("text", "")
            except Exception:
                text = content
            is_alert = should_handle_as_alert("feishu", chat_id, sender_id, text)
            print(f"      is_alert: {is_alert}")
    except Exception as e:
        print(f"  >>> MESSAGE RECEIVED (parse error: {e})")


handler = (
    lark.EventDispatcherHandler.builder(
        app.encrypt_key or "",
        app.verification_token or "",
    )
    .register_p2_im_message_receive_v1(on_message)
    .build()
)

ws_client = WSClient(
    app_id=app.app_id,
    app_secret=app.app_secret,
    event_handler=handler,
    log_level=lark.LogLevel.DEBUG,
    auto_reconnect=True,
)

print("  Starting WebSocket connection...")
print("  (If it hangs here, the connection is failing silently)")
print("  (Check Feishu Open Platform: Event Subscription → WebSocket mode)")
print()

import threading

ws_thread = threading.Thread(target=ws_client.start, daemon=True)
ws_thread.start()

# Wait for connection
time.sleep(3)

if ws_thread.is_alive():
    print("  WebSocket thread is alive (connection likely established)")
    print()
    print("=" * 60)
    print("LISTENING: Send a message in Feishu group now!")
    print("           (Waiting 120 seconds for messages...)")
    print("           Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        for i in range(120):
            time.sleep(1)
            if i > 0 and i % 30 == 0:
                print(f"  ... {120 - i}s remaining, {received_count} messages received so far")
    except KeyboardInterrupt:
        pass

    print(f"\n  Total messages received: {received_count}")
    if received_count == 0:
        print("\n  DIAGNOSIS: WebSocket connected but NO messages received.")
        print("  Possible causes:")
        print("  1. Bot not added to the Feishu group")
        print("  2. In group chat, bot needs @mention to receive messages")
        print("  3. Event 'im.message.receive_v1' not subscribed in Feishu console")
        print("  4. Event subscription type is 'HTTP callback' instead of 'WebSocket'")
        print("     → Go to: https://open.feishu.cn/app → Your App → Event Subscription")
        print("     → Change from 'Request URL' to 'WebSocket'")
else:
    print("  FAIL: WebSocket thread died immediately")
    print("  Check the DEBUG logs above for connection errors")
