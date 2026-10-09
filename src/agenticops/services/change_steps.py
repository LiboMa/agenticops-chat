"""A change request's own steps (MVP-2.6.1 spec §3.D.2): their shape, the commands no review can pass, and the
difference between what was asked for and what the SRE planned — computed here, never by an LLM.

Steps have the fix_plans.steps shape: an ordered list of {"action": str, "command": str}.
"""

import json
import re
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


def plan_steps(steps) -> list:
    """A plan's steps column as a list (legacy rows hold a JSON string)."""
    from agenticops.services.verification import decode_legacy_json
    return decode_legacy_json(steps, list)


def rollback_steps(rollback_plan) -> list:
    """The steps a rollback plan carries. Its shape is free-form: {"steps": [...]}, {"commands": [...]}, a bare
    list, or prose ({"description": "..."}) — prose carries no step, so it adds nothing."""
    value = rollback_plan
    for _ in range(3):  # legacy rows hold a JSON string, sometimes encoded more than once
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    out: list = []
    for key in ("steps", "commands"):
        if isinstance(value.get(key), list):
            out += value[key]
    return out


def unclassified_commands(*step_lists) -> list[str]:
    """Every step, across the given step lists, that no execution tool can classify: its command's tier is
    'unknown', or it has no command, so the executor would decide what to run (2.7.0 E2E observation 3).
    Auto-approval sends a plan holding one to a person. A blocked command is not listed — blocked_commands()
    refuses it outright."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command:
                label = command if command_tier(command) == "unknown" else ""
            else:
                action = " ".join(str(step.get("action") or "").split()) if isinstance(step, dict) else ""
                label = f"(no command) {action}".strip()
            if label and label not in seen:
                seen.append(label)
    return seen


# Commands that take a service down (2.7.0 E2E observation 2: «restore failed half-way» was rolled back by
# scaling both Deployments to 0 — the outage the issue was about). Matched on the lowered, space-collapsed
# command; `0(?!\d)` so `--replicas=10` is not a zero.
_ZERO = r"(?:=|\s+)0(?!\d)"
_OUTAGE_PATTERNS = tuple(re.compile(p) for p in (
    rf"\bscale\b.*--replicas{_ZERO}",                                               # kubectl scale … --replicas=0
    r"\bdelete\s+(?:deployments?|deploy|statefulsets?|sts|daemonsets?|ds|services?|svc)(?:[/.\s]|$)",
    rf"\becs\s+update-service\b.*--desired-count{_ZERO}",
    rf"\bautoscaling\s+(?:set-desired-capacity|update-auto-scaling-group)\b.*--(?:desired-capacity|max-size){_ZERO}",
    r"\beks\s+update-nodegroup-config\b.*desiredsize=0(?!\d)",
    r"\bec2\s+stop-instances\b",
    r"\brds\s+stop-db-(?:instance|cluster)\b",
    rf"\blambda\s+put-function-concurrency\b.*--reserved-concurrent-executions{_ZERO}",
    r"^(?:sudo\s+)?systemctl\s+stop\b",
    r"^(?:sudo\s+)?service\s+\S+\s+stop\b",
))


def outage_commands(*step_lists) -> list[str]:
    """Every command, across the given step lists, that takes a service down: a workload scaled to 0 or deleted,
    an instance / database / service stopped. save_fix_plan refuses a fix plan whose ROLLBACK holds one — undoing
    a fix must never recreate the fault (2.7.0 E2E observation 2)."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command and command not in seen and any(p.search(command.lower()) for p in _OUTAGE_PATTERNS):
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
