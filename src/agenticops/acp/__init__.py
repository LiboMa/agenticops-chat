"""ACP enhanced-backend module (MVP-1.3.0)."""
from agenticops.acp.registry import register_backend
from agenticops.acp.backends.claude_code import ClaudeCodeBackend
from agenticops.acp.backends.kiro_cli import KiroCliBackend
from agenticops.acp.backends.codex import CodexBackend

register_backend("claude-code", ClaudeCodeBackend)
register_backend("kiro-cli", KiroCliBackend)
register_backend("codex", CodexBackend)
