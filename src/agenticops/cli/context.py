"""Chat context and session management for CLI."""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from agenticops.cli.display import TokenUsage
from agenticops.cli.formatters import TABLE_STYLES
from agenticops.config import AGENT_NAMES, VALID_DETAIL_LEVELS, VALID_SCAN_FOCUS

MODEL_ALIASES = {
    "opus": "global.anthropic.claude-opus-4-6-v1",
    "sonnet": "global.anthropic.claude-sonnet-4-6-v1",
    "haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
}


class ChatContext:
    """Context for chat session, holding state like output format."""

    def __init__(self):
        self.output_format = "table"  # table, json, wide
        self.table_style = os.environ.get("AIOPS_TABLE_STYLE", "default")
        self.account = None
        self.detail_level = "medium"  # concise, medium, detailed
        self.scan_focus = "all"  # computing, networking, databases, storage, security, billing, all
        self.current_model = "sonnet"  # friendly name — default matches settings.bedrock_model_id
        self.agent = None  # set after agent creation; enables /model runtime switching
        self.output_history: List[Dict[str, str]] = []  # Store conversation history
        self.pager_threshold = 0  # 0 = auto (terminal height - 8)
        self.auto_pager = True  # Enable auto-truncation for long outputs
        self.last_full_output = ""  # Full output for /less when truncated
        self.token_usage = TokenUsage()  # Track token consumption

    def set_output(self, fmt: str):
        if fmt in ["table", "json", "wide", "yaml"]:
            self.output_format = fmt
            return True
        return False

    def set_detail(self, level: str) -> bool:
        """Set agent output detail level (concise, medium, detailed)."""
        if level in VALID_DETAIL_LEVELS:
            self.detail_level = level
            return True
        return False

    def set_scan_focus(self, focus: str) -> bool:
        """Set scan focus (comma-separated categories or 'all')."""
        parts = [p.strip().lower() for p in focus.split(",") if p.strip()]
        for p in parts:
            if p not in VALID_SCAN_FOCUS:
                return False
        self.scan_focus = ",".join(parts) if parts else "all"
        return True

    def set_model(self, alias: str) -> bool:
        """Switch the agent's Bedrock model at runtime."""
        if alias not in MODEL_ALIASES:
            return False
        if self.agent is None:
            return False
        from strands.models.bedrock import BedrockModel
        from agenticops.config import settings
        self.agent.model = BedrockModel(
            model_id=MODEL_ALIASES[alias],
            region_name=settings.bedrock_region,
            max_tokens=settings.bedrock_max_tokens,
        )
        self.current_model = alias
        return True

    def set_agent_model(self, agent_name: str, alias: str) -> bool:
        """Set a per-agent model override at runtime."""
        if alias not in MODEL_ALIASES or agent_name not in AGENT_NAMES:
            return False
        from agenticops.config import settings
        setattr(settings, f"agent_{agent_name}_model_id", MODEL_ALIASES[alias])
        return True

    def reset_agent_models(self) -> None:
        """Clear all per-agent model overrides."""
        from agenticops.config import settings
        for name in AGENT_NAMES:
            setattr(settings, f"agent_{name}_model_id", "")
            setattr(settings, f"agent_{name}_max_tokens", 0)

    def set_table_style(self, style: str) -> bool:
        """Set table style (default, simple, minimal, double, ascii)."""
        if style in TABLE_STYLES:
            self.table_style = style
            # Also update environment for child functions
            os.environ["AIOPS_TABLE_STYLE"] = style
            return True
        return False

    def add_to_history(self, role: str, content: str):
        """Add message to output history."""
        self.output_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        # Keep last 100 messages
        if len(self.output_history) > 100:
            self.output_history = self.output_history[-100:]

    def get_history(self, count: int = 10) -> List[Dict[str, str]]:
        """Get recent history."""
        return self.output_history[-count:]

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0):
        """Add token usage."""
        self.token_usage.add(input_tokens, output_tokens)

    def get_token_summary(self) -> str:
        """Get token usage summary."""
        return self.token_usage.format()

    def get_token_detailed(self) -> str:
        """Get detailed token usage."""
        return self.token_usage.format_detailed()

    def reset_tokens(self):
        """Reset token counters."""
        self.token_usage.reset()
