"""Display components for CLI - ThinkingDisplay, StatusBar, token tracking."""

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from agenticops.cli.formatters import format_duration, format_number

console = Console()


class ThinkingState(Enum):
    """States for the thinking display."""
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    PROCESSING = "processing"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class TokenUsage:
    """Track token usage across a session."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0

    def add(self, input_tok: int = 0, output_tok: int = 0):
        """Add token counts."""
        self.input_tokens += input_tok
        self.output_tokens += output_tok
        self.total_tokens += input_tok + output_tok
        self.requests += 1

    def reset(self):
        """Reset counters."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.requests = 0

    def format(self) -> str:
        """Format token usage for display."""
        return f"↑{format_number(self.input_tokens)} ↓{format_number(self.output_tokens)} Σ{format_number(self.total_tokens)}"

    def format_detailed(self) -> str:
        """Format detailed token usage."""
        return (
            f"Input: {self.input_tokens:,} tokens\n"
            f"Output: {self.output_tokens:,} tokens\n"
            f"Total: {self.total_tokens:,} tokens\n"
            f"Requests: {self.requests}"
        )


class ThinkingDisplay:
    """Claude Code-style thinking and progress display.

    Shows real-time status updates, tool calls, and thinking process.
    """

    SPINNERS = {
        ThinkingState.THINKING: "dots",
        ThinkingState.TOOL_CALL: "dots2",
        ThinkingState.PROCESSING: "dots3",
        ThinkingState.STREAMING: "dots12",
    }

    STATE_COLORS = {
        ThinkingState.THINKING: "blue",
        ThinkingState.TOOL_CALL: "yellow",
        ThinkingState.PROCESSING: "cyan",
        ThinkingState.STREAMING: "green",
        ThinkingState.COMPLETE: "green",
        ThinkingState.ERROR: "red",
    }

    STATE_ICONS = {
        ThinkingState.THINKING: "◐",
        ThinkingState.TOOL_CALL: "⚙",
        ThinkingState.PROCESSING: "⟳",
        ThinkingState.STREAMING: "▸",
        ThinkingState.COMPLETE: "✓",
        ThinkingState.ERROR: "✗",
    }

    def __init__(self, console: Console, token_usage: Optional[TokenUsage] = None):
        self.console = console
        self.state = ThinkingState.IDLE
        self.steps: List[Dict[str, Any]] = []
        self.current_step = ""
        self.start_time = None
        self._live = None
        self._lock = threading.Lock()
        self.token_usage = token_usage

    def __rich__(self):
        """Make ThinkingDisplay a Rich renderable so Live can animate it."""
        return self._build_display()

    def _build_display(self) -> Group:
        """Build the display content."""
        elements = []

        # Show completed steps
        for step in self.steps:
            icon = self.STATE_ICONS.get(step["state"], "•")
            color = self.STATE_COLORS.get(step["state"], "white")
            duration = step.get("duration", "")
            duration_str = f" [dim]({format_duration(duration)})[/dim]" if duration else ""

            # Use Text.from_markup() to parse Rich markup tags
            if step["state"] == ThinkingState.COMPLETE:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}{duration_str}"))
            elif step["state"] == ThinkingState.ERROR:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}"))
            else:
                elements.append(Text.from_markup(f"  [{color}]{icon}[/{color}] {step['text']}{duration_str}"))

        # Show current step with spinner
        if self.state not in (ThinkingState.IDLE, ThinkingState.COMPLETE, ThinkingState.ERROR):
            spinner_name = self.SPINNERS.get(self.state, "dots")
            color = self.STATE_COLORS.get(self.state, "blue")
            elapsed = ""
            if self.start_time:
                elapsed_secs = time.time() - self.start_time
                elapsed = f" [dim]({format_duration(elapsed_secs)})[/dim]"

            spinner = Spinner(spinner_name, text=Text.from_markup(f"[{color}]{self.current_step}[/{color}]{elapsed}"))
            elements.append(Padding(spinner, (0, 0, 0, 2)))

        return Group(*elements) if elements else Text("")

    @contextmanager
    def live_display(self):
        """Context manager for live display updates."""
        with Live(self, console=self.console, refresh_per_second=10, transient=False) as live:
            self._live = live
            try:
                yield self
            finally:
                self._live = None

    def _update(self):
        """Trigger an immediate display refresh."""
        if self._live:
            self._live.refresh()

    def _complete_current_step(self):
        """Mark current step as complete."""
        if self.current_step:
            duration = time.time() - self.start_time if self.start_time else 0
            self.steps.append({
                "text": self.current_step,
                "state": ThinkingState.COMPLETE,
                "duration": duration,
            })

    def start(self, text: str = "Thinking"):
        """Start thinking display."""
        self.state = ThinkingState.THINKING
        self.current_step = text
        self.start_time = time.time()
        self.steps = []
        self._update()

    def thinking(self, text: str):
        """Update thinking status."""
        with self._lock:
            self.state = ThinkingState.THINKING
            self.current_step = text
            self._update()

    def tool_call(self, tool_name: str, args: str = ""):
        """Show tool call status."""
        with self._lock:
            # Complete previous step if any
            if self.current_step and self.state != ThinkingState.IDLE:
                self._complete_current_step()

            self.state = ThinkingState.TOOL_CALL
            args_str = f" ({args})" if args else ""
            self.current_step = f"Calling {tool_name}{args_str}"
            self.start_time = time.time()
            self._update()

    def processing(self, text: str):
        """Show processing status."""
        with self._lock:
            if self.current_step and self.state == ThinkingState.TOOL_CALL:
                self._complete_current_step()

            self.state = ThinkingState.PROCESSING
            self.current_step = text
            self.start_time = time.time()
            self._update()

    def streaming(self, text: str = "Generating response"):
        """Show streaming status."""
        with self._lock:
            if self.current_step:
                self._complete_current_step()

            self.state = ThinkingState.STREAMING
            self.current_step = text
            self.start_time = time.time()
            self._update()

    def step(self, text: str, state: ThinkingState = ThinkingState.COMPLETE):
        """Add a completed step."""
        with self._lock:
            duration = time.time() - self.start_time if self.start_time else 0
            self.steps.append({
                "text": text,
                "state": state,
                "duration": duration,
            })
            self.start_time = time.time()
            self._update()

    def complete(self, text: str = "Done"):
        """Mark as complete."""
        with self._lock:
            if self.current_step:
                self._complete_current_step()

            self.steps.append({
                "text": text,
                "state": ThinkingState.COMPLETE,
                "duration": 0,
            })
            self.state = ThinkingState.COMPLETE
            self._update()

    def error(self, text: str):
        """Show error state."""
        with self._lock:
            if self.current_step:
                self._complete_current_step()

            self.steps.append({
                "text": text,
                "state": ThinkingState.ERROR,
                "duration": 0,
            })
            self.state = ThinkingState.ERROR
            self._update()


class StatusBar:
    """Status bar for displaying session info and token usage."""

    def __init__(self, token_usage: TokenUsage):
        self.token_usage = token_usage
        self.start_time = datetime.now()
        self.account_name: Optional[str] = None

    def render(self) -> str:
        """Render status bar string."""
        elapsed = datetime.now() - self.start_time
        elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"

        parts = []

        # Account context
        if self.account_name:
            parts.append(f"[cyan]{self.account_name}[/cyan]")

        # Token usage
        parts.append(f"[dim]Tokens:[/dim] {self.token_usage.format()}")

        # Session time
        parts.append(f"[dim]Session:[/dim] {elapsed_str}")

        return " │ ".join(parts)

    def print(self):
        """Print status bar to console."""
        console.print(f"[dim]─[/dim] {self.render()} [dim]─[/dim]", justify="right")
