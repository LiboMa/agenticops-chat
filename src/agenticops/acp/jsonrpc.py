"""Newline-delimited JSON-RPC 2.0 framing over asyncio streams.

ACP transport rule: each message is a single-line JSON object terminated by '\\n',
with NO embedded newlines. Non-JSON / blank lines on the stream are skipped
(the agent must keep stdout clean, but be defensive).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional


def encode_message(msg: dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC message to a single newline-terminated line."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


async def read_message(reader: asyncio.StreamReader) -> Optional[dict[str, Any]]:
    """Read the next JSON object line. Returns None at EOF. Skips blank/non-JSON lines."""
    while True:
        raw = await reader.readline()
        if not raw:
            return None
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue  # defensive: ignore stray non-protocol stdout
