"""Kiro CLI enhanced backend — drives `kiro-cli acp` via the shared AcpClient.

kiro-cli 2.4.0 speaks ACP natively (`kiro-cli acp`). Auth uses kiro-cli's own
login state (IAM Identity Center), so no extra credential env is injected here.
`--trust-all-tools` (in the default args) auto-approves tool permission requests.
"""
from __future__ import annotations

from typing import AsyncIterator

from agenticops.acp.client import AcpClient
from agenticops.acp.types import BackendCapabilities, EnhancedEvent
from agenticops.config import settings


class KiroCliBackend:
    name = "kiro-cli"

    def __init__(self):
        self._client = AcpClient(
            command=settings.acp_kiro_command,
            args=list(settings.acp_kiro_args),
            env_extra={},  # kiro-cli uses its own login state
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
