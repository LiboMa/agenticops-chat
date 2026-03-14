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
    """Track token usage across a session, including cache metrics and per-agent breakdown."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0
    per_agent: dict = field(default_factory=dict)  # agent_name → {input, output, cache_read, cache_write, requests}

    def add(self, input_tok: int = 0, output_tok: int = 0,
            cache_read: int = 0, cache_write: int = 0, agent_name: str = "main"):
        """Add token counts with cache and per-agent tracking."""
        self.input_tokens += input_tok
        self.output_tokens += output_tok
        self.total_tokens += input_tok + output_tok
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write
        self.requests += 1

        if agent_name not in self.per_agent:
            self.per_agent[agent_name] = {
                "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "requests": 0,
            }
        a = self.per_agent[agent_name]
        a["input"] += input_tok
        a["output"] += output_tok
        a["cache_read"] += cache_read
        a["cache_write"] += cache_write
        a["requests"] += 1

    def reset(self):
        """Reset counters."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.requests = 0
        self.per_agent = {}

    def format(self) -> str:
        """Format token usage for status bar."""
        cache_info = f" 🗄{format_number(self.cache_read_tokens)}" if self.cache_read_tokens else ""
        return f"↑{format_number(self.input_tokens)} ↓{format_number(self.output_tokens)} Σ{format_number(self.total_tokens)}{cache_info}"

    def format_detailed(self) -> str:
        """Format detailed token usage with per-agent breakdown and cost estimate."""
        from agenticops.config import get_agent_model_config
        lines = [
            f"Input:       {self.input_tokens:>10,} tokens",
            f"Output:      {self.output_tokens:>10,} tokens",
            f"Total:       {self.total_tokens:>10,} tokens",
            f"Cache Read:  {self.cache_read_tokens:>10,} tokens",
            f"Cache Write: {self.cache_write_tokens:>10,} tokens",
            f"Requests:    {self.requests:>10}",
        ]
        if self.per_agent:
            lines.append("")
            lines.append("Per-Agent Breakdown:")
            # Cost rates per 1M tokens (input/output)
            COST_TABLE = {
                "claude-opus-4-6": (15.0, 75.0, 1.50),      # input, output, cache_read
                "claude-sonnet-4-6": (3.0, 15.0, 0.30),
                "claude-haiku-4-5": (0.80, 4.0, 0.08),
            }
            total_cost = 0.0
            for name, a in self.per_agent.items():
                model_id, _ = get_agent_model_config(name)
                short = model_id.split(".")[-1] if "." in model_id else model_id
                # Match cost tier
                cost_key = None
                for k in COST_TABLE:
                    if k in short:
                        cost_key = k
                        break
                if cost_key:
                    inp_rate, out_rate, cache_rate = COST_TABLE[cost_key]
                    cost = (a["input"] * inp_rate + a["output"] * out_rate + a["cache_read"] * cache_rate) / 1_000_000
                    total_cost += cost
                    cost_str = f"  ${cost:.4f}"
                else:
                    cost_str = ""
                cache_str = f"  cache_read={a['cache_read']:,}" if a["cache_read"] else ""
                lines.append(
                    f"  {name:10s} ↑{a['input']:>8,} ↓{a['output']:>8,}{cache_str}  ({short}){cost_str}"
                )
            if total_cost > 0:
                lines.append(f"\nEstimated Cost: ${total_cost:.4f}")
        return "\n".join(lines)


class StreamingCallbackHandler:
    """CLI callback: animated spinner during thinking/tools, buffered streaming for text."""

    def __init__(self, console: Console):
        self.console = console
        self._phase = "idle"       # idle -> thinking -> streaming -> done
        self._tool_count = 0
        self._start_time = 0.0
        self._step_start = 0.0
        self._current_step = ""
        self._live: Optional[Live] = None
        self._buf: list = []       # text buffer for batched output
        self._last_flush = 0.0

    def _show_spinner(self, text: str, style: str = "dots"):
        """Show/update animated spinner via Rich Live."""
        spinner = Spinner(style, text=Text.from_markup(text))
        padded = Padding(spinner, (0, 0, 0, 2))
        if self._live:
            self._live.update(padded)
        else:
            self._live = Live(padded, console=self.console, transient=True, refresh_per_second=10)
            self._live.start()

    def _complete_step(self):
        """Stop spinner, print completed step line."""
        if self._live:
            self._live.stop()
            self._live = None
        if self._current_step:
            elapsed = time.time() - self._step_start
            self.console.print(
                f"  [green]\u2713[/green] {self._current_step} [dim]({format_duration(elapsed)})[/dim]"
            )
            self._current_step = ""

    def _flush_buf(self):
        """Flush buffered text to stdout."""
        if self._buf:
            import sys
            sys.stdout.write("".join(self._buf))
            sys.stdout.flush()
            self._buf.clear()
            self._last_flush = time.time()

    def start(self):
        """Call before agent() to show initial spinner immediately."""
        self._phase = "thinking"
        self._current_step = "Thinking"
        self._start_time = time.time()
        self._step_start = time.time()
        self._show_spinner("[blue]\u25d0 Thinking[/blue]")

    def stop(self):
        """Cleanup on exception or interruption."""
        self._flush_buf()
        if self._live:
            self._live.stop()
            self._live = None
        if self._phase == "streaming":
            print()  # ensure final newline
        self._phase = "done"

    def __call__(self, **kwargs):
        data = kwargs.get("data", "")
        complete = kwargs.get("complete", False)
        event = kwargs.get("event") or {}
        tool_use = event.get("contentBlockStart", {}).get("start", {}).get("toolUse")

        # Tool call event -> show as spinner step
        if tool_use:
            self._flush_buf()
            if self._current_step:
                self._complete_step()
            name = tool_use.get("name", "unknown")
            self._tool_count += 1
            self._current_step = name
            self._step_start = time.time()
            self._phase = "thinking"
            self._show_spinner(f"[yellow]\u2699 {name}[/yellow]", "dots2")

        # Text data -> stream to stdout with buffering
        if data:
            if self._phase != "streaming":
                self._flush_buf()
                if self._current_step:
                    self._complete_step()
                self._phase = "streaming"
                print()  # blank line before response
            self._buf.append(data)
            now = time.time()
            if now - self._last_flush > 0.05 or "\n" in data:
                self._flush_buf()

        # Complete
        if complete:
            self._flush_buf()
            if self._live:
                self._live.stop()
                self._live = None
            if self._phase == "streaming":
                print()  # final newline
            self._phase = "done"


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
