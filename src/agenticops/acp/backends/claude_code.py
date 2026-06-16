"""Claude Code enhanced backend — drives `claude-agent-acp` over Bedrock via AcpClient."""
from __future__ import annotations

from typing import AsyncIterator

from agenticops.acp.client import AcpClient
from agenticops.acp.types import BackendCapabilities, EnhancedEvent
from agenticops.config import settings


class ClaudeCodeBackend:
    name = "claude-code"

    def __init__(self):
        env_extra = {}
        if settings.acp_use_bedrock:
            env_extra["CLAUDE_CODE_USE_BEDROCK"] = "1"
            region = getattr(settings, "bedrock_region", "") or "us-east-1"
            env_extra.setdefault("AWS_REGION", region)
        self._client = AcpClient(
            command=settings.acp_claude_command,
            args=list(settings.acp_claude_args),
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
