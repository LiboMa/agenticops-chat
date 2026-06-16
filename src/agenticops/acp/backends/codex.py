"""Codex enhanced backend — drives `@zed-industries/codex-acp` via the shared AcpClient.

codex-acp is an ACP-compatible coding agent powered by Codex; it needs an OpenAI
credential. We pass through OPENAI_API_KEY / OPENAI_BASE_URL from the environment
if present. If no key is configured, the subprocess will error and `enhanced_task`
surfaces a clear message (the turn never crashes).
"""
from __future__ import annotations

import os
from typing import AsyncIterator

from agenticops.acp.client import AcpClient
from agenticops.acp.types import BackendCapabilities, EnhancedEvent
from agenticops.config import settings


class CodexBackend:
    name = "codex"

    def __init__(self):
        env_extra = {}
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID"):
            v = os.environ.get(key)
            if v:
                env_extra[key] = v
        self._client = AcpClient(
            command=settings.acp_codex_command,
            args=list(settings.acp_codex_args),
            env_extra=env_extra,
            auto_approve=settings.acp_auto_approve_permissions,
            timeout=settings.acp_timeout_seconds,
        )

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(streaming=True, plan=True, permissions=True, tools=False)

    async def run(self, task: str, context: str) -> AsyncIterator[EnhancedEvent]:
        prompt = f"{task}\n\n---\nContext:\n{context}" if context else task
        async for ev in self._client.run(prompt):
            yield ev

    async def cancel(self) -> None:
        await self._client.cancel()
