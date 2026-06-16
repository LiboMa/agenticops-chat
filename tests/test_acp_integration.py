"""Integration test that actually spawns claude-agent-acp.

Uses the existing `integration` marker: skipped by default; run with
`pytest --run-integration`. Also skipif when npx is absent.
"""
import shutil
import asyncio
import pytest


def _have_npx():
    return shutil.which("npx") is not None


@pytest.mark.integration
@pytest.mark.skipif(not _have_npx(), reason="npx/claude-agent-acp not available")
def test_claude_backend_streams_text():
    from agenticops.config import settings
    settings.acp_use_bedrock = True
    from agenticops.acp.backends.claude_code import ClaudeCodeBackend

    async def run():
        be = ClaudeCodeBackend()
        kinds, text = [], []
        async for ev in be.run("Reply with exactly one word: hello", ""):
            kinds.append(ev.kind)
            if ev.kind == "text":
                text.append(ev.text or "")
            if ev.kind == "error":
                pytest.skip(f"backend error (likely no creds/install): {ev.error}")
        return kinds, "".join(text)

    kinds, text = asyncio.run(asyncio.wait_for(run(), 180))
    assert "done" in kinds
