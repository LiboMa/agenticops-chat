"""Chat context and session management for CLI."""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from agenticops.cli.display import TokenUsage
from agenticops.cli.formatters import TABLE_STYLES


class ChatContext:
    """Context for chat session, holding state like output format."""

    def __init__(self):
        self.output_format = "table"  # table, json, wide
        self.table_style = os.environ.get("AIOPS_TABLE_STYLE", "default")
        self.account = None
        self.verbose = False
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
