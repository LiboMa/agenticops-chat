"""ACP enhanced-backend module (MVP-1.3.0)."""
from agenticops.acp.registry import register_backend
from agenticops.acp.backends.claude_code import ClaudeCodeBackend

register_backend("claude-code", ClaudeCodeBackend)
