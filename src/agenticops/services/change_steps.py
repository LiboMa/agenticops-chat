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


def _raw_command(step) -> str:
    return str((step.get("command") or "") if isinstance(step, dict) else (step or ""))


def _command(step) -> str:
    return " ".join(_raw_command(step).split())


# skills/security.SHELL_READONLY_COMMANDS is the run-time gate of run_on_host: it answers «may this run without
# asking». A plan step's label — and the auto-approval floor — ask something narrower: «can this line change
# anything». Only the entries that cannot write whatever their arguments keep 'readonly' here; the others (find
# -delete, tee, xargs rm, journalctl --vacuum-size, sort -o, date -s, curl -s -X DELETE, env VAR=1 cmd …) are
# 'unknown': a person looks. tests/test_plan_step_tiers.py fails when the run-time list gains an entry nobody put
# on one side.
HOST_CANNOT_WRITE = frozenset({
    "ls", "cat", "head", "tail", "more", "file", "stat", "wc", "locate", "which", "whereis", "readlink",
    "ps", "top", "htop", "pgrep", "pidof", "lsof",
    "uname", "uptime", "who", "w", "whoami", "id", "groups",
    "free", "vmstat", "iostat", "mpstat", "nproc", "lscpu", "df", "du", "lsblk", "fdisk -l",
    "netstat", "ping", "traceroute", "tracepath", "mtr", "dig", "nslookup", "host",
    "last", "lastb",
    "grep", "egrep", "fgrep", "cut", "tr", "diff", "comm",
    "docker ps", "docker logs", "docker inspect", "docker images", "docker stats", "docker top", "docker port",
    "docker diff", "docker history", "docker network ls", "docker network inspect", "docker volume ls",
    "docker volume inspect",
    "ssh-add -l", "ssh-keygen -lf", "ssh-keygen -l", "ssh-keyscan", "sshd -t",
    "openssl s_client", "printenv",
})
HOST_CAN_WRITE = frozenset({
    "less", "find", "hostname", "date", "timedatectl", "hostnamectl", "sar", "blkid", "mount",
    "ss", "ip", "ifconfig", "nmap", "arp", "route", "iperf", "iperf3", "ethtool", "tc",
    "journalctl", "dmesg", "lastlog",
    "awk", "sed -n", "sort", "uniq", "tee", "xargs",
    "strace", "ltrace", "tcpdump", "sysctl -a",
    "curl -s", "curl --silent", "wget -q", "env", "set",
})

_CONTINUED = re.compile(r"\\\r?\n")                                             # a line continued with a backslash
_HARMLESS_REDIRECT = re.compile(r"(?:[12]?>{1,2}\s*/dev/null|&>\s*/dev/null|2>&1)")  # sends nothing anywhere that matters


def _shell_would_split(text: str) -> bool:
    """True when a shell would read more than one simple command in `text`, or send its output somewhere: an
    unquoted ; & | < > ( ), a backtick or $( outside single quotes. Quoted text is data (a JMESPath `--query` is
    full of | & > and backticks) and `2>/dev/null` / `2>&1` change nothing, so neither counts."""
    text = _HARMLESS_REDIRECT.sub(" ", text)
    quote, i = None, 0
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1                                   # the next character is literal
        elif quote == '"':
            if c == '"':
                quote = None
            elif c == "`" or text.startswith("$(", i):
                return True                          # still runs inside double quotes
        elif c in "'\"":
            quote = c
        elif c in ";&|<>()`":
            return True
        i += 1
    return False


def _host_entry(lowered: str) -> str:
    """The run-time list's entry `lowered` begins with (the longest, as classify_shell_command picks it)."""
    from agenticops.skills.security import SHELL_READONLY_COMMANDS

    best = ""
    for entry in SHELL_READONLY_COMMANDS:
        if (lowered == entry or lowered.startswith(entry + " ")) and len(entry) > len(best):
            best = entry
    return best


def command_tier(command: str) -> str:
    """The execution tier ('blocked' | 'write' | 'readonly' | 'unknown') of the tool that would run `command`.

    The tools' classifiers read how the line begins. 'readonly' is therefore kept only for a line that is ONE
    command a shell would not split, redirect or substitute into, on one line — and, on a host, one whose first
    words cannot write whatever follows (HOST_CANNOT_WRITE). Anything else that began like a read is 'unknown'.
    A write or a blocked command stays what it is: the checks only move a step toward «a person looks»."""
    from agenticops.skills.security import classify_kubectl_command, classify_shell_command
    from agenticops.tools.aws_cli_tool import _classify_command

    text = _CONTINUED.sub(" ", command or "")
    flat = " ".join(text.split())
    head = flat.split(None, 1)[0].lower() if flat else ""
    if head == "aws":
        tier = _classify_command(flat)
    elif head == "kubectl":
        tier = classify_kubectl_command(flat)
    else:
        tier = classify_shell_command(flat)
        if tier == "readonly" and _host_entry(flat.lower()) not in HOST_CANNOT_WRITE:
            tier = "unknown"
    if tier == "readonly" and (len([line for line in text.splitlines() if line.strip()]) > 1 or _shell_would_split(text)):
        tier = "unknown"
    return tier


def step_tier(step) -> str:
    """One plan step's tier as a page shows it beside the step: its command's tier, and 'unknown' for a step with
    no command — the executor would decide what to run. The auto-approval floor (unclassified_commands) reads
    this same answer."""
    raw = _raw_command(step)
    return command_tier(raw) if raw.strip() else "unknown"


def step_tiers(steps) -> list[str]:
    """One tier per step of a plan's steps column, in order (MVP-2.9.0: FixPlanResponse.step_tiers)."""
    return [step_tier(s) for s in plan_steps(steps)]


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
                label = command if step_tier(step) == "unknown" else ""
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
