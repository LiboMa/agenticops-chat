"""A change request's own steps (MVP-2.6.1 spec §3.D.2): their shape, the commands no review can pass, and the
difference between what was asked for and what the SRE planned — computed here, never by an LLM.

Steps have the fix_plans.steps shape: an ordered list of {"action": str, "command": str}.
"""

from difflib import SequenceMatcher
from typing import Optional

MAX_STEPS = 50
MAX_COMMAND_CHARS = 2000
MAX_ACTION_CHARS = 500


def normalize_steps(raw) -> Optional[list[dict]]:
    """The requester's steps as stored, or None when none were given. Raises ValueError on a bad shape."""
    if raw is None or raw == []:
        return None
    if not isinstance(raw, list):
        raise ValueError("proposed_steps must be a list of {action, command} steps")
    if len(raw) > MAX_STEPS:
        raise ValueError(f"too many proposed steps (max {MAX_STEPS})")
    steps = []
    for n, step in enumerate(raw, 1):
        if not isinstance(step, dict):
            raise ValueError(f"proposed step {n} must be an object with a command")
        command = str(step.get("command") or "").strip()
        if not command:
            raise ValueError(f"proposed step {n} has no command")
        if len(command) > MAX_COMMAND_CHARS:
            raise ValueError(f"proposed step {n} command too long (max {MAX_COMMAND_CHARS} characters)")
        steps.append({"action": str(step.get("action") or "").strip()[:MAX_ACTION_CHARS], "command": command})
    return steps


def _command(step) -> str:
    return " ".join(str((step.get("command") or "") if isinstance(step, dict) else (step or "")).split())


def command_tier(command: str) -> str:
    """The execution tier ('blocked' | 'write' | 'readonly' | 'unknown') of the tool that would run `command`."""
    from agenticops.skills.security import classify_kubectl_command, classify_shell_command
    from agenticops.tools.aws_cli_tool import _classify_command

    head = command.split(None, 1)[0].lower() if command.strip() else ""
    if head == "aws":
        return _classify_command(command)
    if head == "kubectl":
        return classify_kubectl_command(command)
    return classify_shell_command(command)


def blocked_commands(*step_lists) -> list[str]:
    """Every command, across the given step lists, that its execution tool refuses outright."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command and command not in seen and command_tier(command) == "blocked":
                seen.append(command)
    return seen


def diff_steps(proposed, planned) -> dict:
    """What the plan changed relative to the request, by command and in order. A replaced run pairs its steps
    one-to-one as modified; the rest of it is added / removed. Step numbers are 1-based."""
    a, b = [_command(s) for s in proposed or []], [_command(s) for s in planned or []]
    added, removed, modified, unchanged = [], [], [], 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        modified += [{"proposed_step": i1 + k + 1, "plan_step": j1 + k + 1, "proposed": a[i1 + k], "plan": b[j1 + k]}
                     for k in range(pairs)]
        removed += [{"proposed_step": i + 1, "command": a[i]} for i in range(i1 + pairs, i2)]
        added += [{"plan_step": j + 1, "command": b[j]} for j in range(j1 + pairs, j2)]
    return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}
