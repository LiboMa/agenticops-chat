"""Security classification for shell and kubectl commands.

Three-tier model mirroring src/agenticops/tools/aws_cli_tool.py:
- readonly: Safe diagnostic/inspection commands (auto-execute)
- write: Commands that modify state (require confirmation)
- blocked: Dangerous/destructive commands (rejected outright)

Unknown commands default to 'write' (require confirmation).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

# ── Shell Command Classification ─────────────────────────────────────

SHELL_READONLY_COMMANDS = {
    # File/directory inspection
    "ls", "cat", "head", "tail", "less", "more", "file", "stat", "wc",
    "find", "locate", "which", "whereis", "readlink",
    # Process inspection
    "ps", "top", "htop", "pgrep", "pidof", "lsof",
    # System info
    "uname", "hostname", "uptime", "who", "w", "whoami", "id", "groups",
    "date", "timedatectl", "hostnamectl",
    # Memory/CPU/disk
    "free", "vmstat", "iostat", "mpstat", "sar", "nproc", "lscpu",
    "df", "du", "lsblk", "blkid", "fdisk -l", "mount",
    # Network diagnostics
    "netstat", "ss", "ip", "ifconfig", "ping", "traceroute", "tracepath",
    "mtr", "dig", "nslookup", "host", "nmap", "arp", "route",
    "iperf", "iperf3", "ethtool", "tc",
    # Logs
    "journalctl", "dmesg", "last", "lastb", "lastlog",
    # Text processing (read-only)
    "grep", "egrep", "fgrep", "awk", "sed -n", "sort", "uniq", "cut",
    "tr", "tee", "xargs", "diff", "comm",
    # System diagnostics
    "strace", "ltrace", "tcpdump", "sysctl -a",
    # Docker (read-only)
    "docker ps", "docker logs", "docker inspect", "docker images",
    "docker stats", "docker top", "docker port", "docker diff",
    "docker history", "docker network ls", "docker network inspect",
    "docker volume ls", "docker volume inspect",
    # SSH diagnostics (read-only) — lowercase: classifier lowercases input
    "ssh-add -l",
    "ssh-keygen -lf", "ssh-keygen -l",
    "ssh-keyscan",
    "sshd -t",
    # Misc
    "curl -s", "curl --silent", "wget -q", "openssl s_client",
    "env", "printenv", "set",
}

SHELL_WRITE_COMMANDS = {
    # Service management
    "systemctl restart", "systemctl stop", "systemctl start",
    "systemctl enable", "systemctl disable", "systemctl reload",
    "service",
    # Process management
    "kill", "killall", "pkill",
    # File operations
    "cp", "mv", "chmod", "chown", "chgrp", "mkdir", "touch",
    "ln", "tar", "zip", "unzip", "gzip", "gunzip",
    # SSH key/config modifications — lowercase: classifier lowercases input
    "ssh-keygen -r", "ssh-add -d",
    "ssh-add",  # adding keys changes agent state
    "scp", "rsync",
    # Network modifications
    "iptables", "ip6tables", "nft", "firewall-cmd",
    "ip link set", "ip addr add", "ip route add",
    # Docker (write)
    "docker exec", "docker run", "docker stop", "docker start",
    "docker restart", "docker rm", "docker rmi",
    "docker pull", "docker push", "docker build",
    "docker-compose", "docker compose",
    # Package management
    "apt", "apt-get", "yum", "dnf", "pip", "npm",
    # Cron
    "crontab",
}

SHELL_BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",
    r"rm\s+-rf\s+/\*",
    r"rm\s+.*--no-preserve-root",
    r"rm\s+(-\S+\s+)*-\S*(rf|fr)\S*\s+/\s*(\s|$)",
    "mkfs",
    r"dd\s+if=",
    "shutdown", "reboot", "poweroff", "halt", "init 0", "init 6",
    r"^passwd\b",
    r"curl.*\|\s*bash",
    r"curl.*\|\s*sh",
    r"wget.*\|\s*bash",
    r"wget.*\|\s*sh",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r">\s*/dev/sd",
    r">\s*/dev/null\s*2>&1\s*<\s*/dev/null",
    "format c:",
    r"chmod\s+-r\s+777\s+/\s*$",
    r"chown\s+-r.*\s+/\s*$",
]


def classify_shell_command(cmd: str) -> str:
    """Classify a shell command as 'blocked', 'write', 'readonly', or 'unknown'.

    Args:
        cmd: The shell command string.

    Returns:
        Security tier: 'blocked', 'write', 'readonly', or 'unknown'.
    """
    cmd_stripped = cmd.strip()
    cmd_lower = cmd_stripped.lower()

    # Check blocked patterns first
    for pattern in SHELL_BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            return "blocked"

    # Check both readonly and write, preferring the longest prefix match
    # so that "ip link set" (write) wins over "ip" (readonly).
    best_match = None
    best_len = 0
    for ro_cmd in SHELL_READONLY_COMMANDS:
        if cmd_lower == ro_cmd or cmd_lower.startswith(ro_cmd + " "):
            if len(ro_cmd) > best_len:
                best_match = "readonly"
                best_len = len(ro_cmd)
    for wr_cmd in SHELL_WRITE_COMMANDS:
        if cmd_lower == wr_cmd or cmd_lower.startswith(wr_cmd + " "):
            if len(wr_cmd) > best_len:
                best_match = "write"
                best_len = len(wr_cmd)

    if best_match:
        return best_match

    # Unknown defaults to write (require confirmation)
    return "unknown"


# ── kubectl Command Classification ───────────────────────────────────

KUBECTL_READONLY_SUBCOMMANDS = {
    "get", "describe", "logs", "top", "explain", "cluster-info",
    "auth can-i", "api-resources", "api-versions", "version",
    "config view", "config get-contexts", "config current-context",
    "events", "diff",
}

KUBECTL_WRITE_SUBCOMMANDS = {
    "apply", "create", "delete", "patch", "replace", "set",
    "scale", "autoscale", "rollout", "label", "annotate", "taint",
    "cordon", "uncordon", "drain", "exec", "cp", "port-forward",
    "edit", "run",
}

KUBECTL_BLOCKED_PATTERNS = [
    r"delete\s+namespace\s+kube-system",
    r"delete\s+ns\s+kube-system",
    r"delete\s+--all\s+--all-namespaces",
    r"delete\s+--all\s+-a",
    r"delete\s+clusterrole\b",
    r"delete\s+clusterrolebinding\b",
    r"delete\s+crd\s+--all",
    r"delete\s+node\s+--all",
]


def classify_kubectl_command(cmd: str) -> str:
    """Classify a kubectl command as 'blocked', 'write', 'readonly', or 'unknown'.

    Args:
        cmd: The kubectl command string (without 'kubectl' prefix).

    Returns:
        Security tier: 'blocked', 'write', 'readonly', or 'unknown'.
    """
    cmd_stripped = cmd.strip()
    cmd_lower = cmd_stripped.lower()

    # Strip leading 'kubectl' if present
    if cmd_lower.startswith("kubectl "):
        cmd_lower = cmd_lower[len("kubectl "):]

    # Check blocked patterns first
    for pattern in KUBECTL_BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            return "blocked"

    # Check readonly subcommands
    for ro_cmd in KUBECTL_READONLY_SUBCOMMANDS:
        if cmd_lower == ro_cmd or cmd_lower.startswith(ro_cmd + " "):
            return "readonly"

    # Check write subcommands
    for wr_cmd in KUBECTL_WRITE_SUBCOMMANDS:
        if cmd_lower == wr_cmd or cmd_lower.startswith(wr_cmd + " "):
            return "write"

    return "unknown"


# ── SKILL.md Body Scanning ───────────────────────────────────────────

# Promotion-gate-only destructive patterns. Broader than the shared runtime
# SHELL_BLOCKED_PATTERNS (which the spec defers changing) — this layer exists
# solely to keep a dangerous *published* skill out of the catalog. Runtime
# execution still re-classifies per command via classify_shell_command, so this
# is defense-in-depth, not the sole gate.
_SKILL_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$home|\*)",  # rm -rf on /, ~, $HOME, * (any abs/home/glob target)
    r"\brm\s+-[a-z]*f?r[a-z]*\s+(/|~|\$home|\*)",  # flag-order variant (-fr)
    r"\bdd\s+.*\bof=/dev/",                          # dd onto a device
    r">\s*/dev/(sd|nvme|hd|disk)",                  # redirect onto a block device
    r"\bmkfs\b", r"\bfdisk\b.*-",                    # filesystem/partition ops
    r"\bchmod\s+-[a-z]*r[a-z]*\s+777\s+/",         # recursive 777 on /
    r"\bchown\s+-[a-z]*r[a-z]*\s+.*\s+/\s*$",      # recursive chown of /
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",                 # fork bomb
    r"(curl|wget)\b.*\|\s*(bash|sh)\b",             # pipe-to-shell
    r"\b(shutdown|reboot|poweroff|halt)\b",
]


def scan_skill_safety(body: str) -> dict:
    """Scan a SKILL.md body's fenced command blocks for destructive commands.

    Returns {"safe": bool, "findings": [str]}. A skill is unsafe if any command
    line classifies as 'blocked' by the shared classifier OR matches a
    promotion-gate destructive pattern (broader, catches ``rm -rf /etc`` etc.).
    Scans ```bash/sh/shell``` fences plus untagged ``` fences (commands are
    often shown without a language tag).
    """
    findings: list[str] = []
    # bash/sh/shell-tagged fences AND bare ``` fences (no language tag)
    for m in re.finditer(r"```(?:bash|sh|shell)?\n(.*?)```", body, re.DOTALL):
        for line in m.group(1).splitlines():
            cmd = line.strip()
            if not cmd or cmd.startswith("#"):
                continue
            cmd = cmd[1:].strip() if cmd.startswith("$") else cmd
            if not cmd:
                continue
            low = cmd.lower()
            matched = False
            for pat in _SKILL_DESTRUCTIVE_PATTERNS:
                if re.search(pat, low):
                    findings.append(f"destructive command: {cmd[:80]}")
                    matched = True
                    break
            if matched:
                continue
            try:
                tier = classify_shell_command(cmd)
            except Exception:
                continue
            if tier == "blocked":
                findings.append(f"blocked command: {cmd[:80]}")
    return {"safe": len(findings) == 0, "findings": findings}


# ── Bundle Scanning (SKILL.md + packaged scripts) ─────────────────

# Deterministic, zero-LLM analysis of a whole skill package. `.py` payloads are
# analysed structurally with `ast` (fix round 1) rather than line-by-line, because
# every text pattern was defeated by ordinary — often *preferred* — idioms: the
# argv-list form of subprocess.run, `os.path.join` instead of a path literal,
# `from os import system`, or nothing more than a formatter wrapping one long call.
#
# KNOWN LIMITATIONS, deliberate and fail-closed unless noted (see also the
# scan_skill_bundle docstring):
#   * Deliberate obfuscation is OUT OF SCOPE and passes clean: `getattr(os,
#     'sys'+'tem')`, base64/codecs payloads, `__import__('os').system(...)`.
#     Do not read this gate as complete — a human still approves every promote.
#   * Write-then-execute (a script that writes p.sh then runs `bash p.sh`) is not
#     detected: separating codegen from a dropper needs dataflow, and flagging
#     `subprocess.run(['bash', <var>])` would reject legitimate skills. FAIL-OPEN.
#   * `.sh` scanning is line-based: prose and trailing comments can be flagged
#     (`echo "never run rm -rf / on prod"`), because telling a string literal from
#     a command needs a shell parser. FAIL-CLOSED.
#   * Network capability for the secret-material rule is inferred from imports and
#     shell-out calls, so a module named in a comment cannot arm it any more, but a
#     script that reaches the network some other way will not. FAIL-OPEN at the edges.
#   * `shutil.rmtree` on a target that does not fold to a literal is not flagged;
#     flagging every rmtree would reject legitimate cleanup. FAIL-OPEN.
#   * `shell=<variable>` (`subprocess.run(cmd, shell=use_shell)`) is not flagged — the
#     pre-`ast` regex missed it too, so it is a standing gap, NOT a regression. Only a
#     constant `True`, or an expression containing one (`True if … else False`), counts;
#     "any value that is not False" would reject legitimate code. FAIL-OPEN.
#   * A deep left-nested `BinOp` chain (~1500+ terms) exhausts `_py_fold`'s recursion and
#     collapses the whole file to one `unreadable script: maximum recursion depth`
#     finding, hiding any real payload in the same file behind a generic reason.
#     FAIL-CLOSED (the package is still rejected).
#   * The dynamic-exec rule matches a bare trailing `eval`/`exec`, so a method of that
#     name reached through a plain name (`c.eval(x)`) is flagged. FAIL-CLOSED, and the
#     same breadth the pre-`ast` regex had.
#   * Every finding emitted today carries `tier == "blocked"`, so `safe` is exactly
#     `len(findings) == 0`. If a lower tier is ever emitted, `safe` MUST be redefined
#     to `not any(f["tier"] == "blocked" ...)` IN THE SAME COMMIT, or the gate
#     silently starts rejecting write-tier skills.

_SECRET_MATERIAL_REASON = "references cloud secret material"
_PY_SECRET_PATTERN = r"AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN"

# Path rules — matched against constant-folded strings on the `.py` side and against
# raw lines on the `.sh` side. `~/.aws/config` is deliberately NOT here: it holds
# region/profile/role_arn, not credential material, and once these rules were mirrored
# onto `.sh` the ordinary `export AWS_CONFIG_FILE="$HOME/.aws/config"` idiom became a
# false positive. A gate that rejects normal ops scripts teaches operators to click
# through it. `~/.aws/credentials` still flags, as do the secret-material env names.
_PY_PATH_PATTERNS: list[tuple[str, str]] = [
    (r"\.aws[/\\]credentials", "reads a cloud credential file"),
    (r"\.ssh[/\\]id_[a-z0-9_]+", "reads an SSH private key"),
    (r"/etc/(shadow|sudoers)", "reads a privileged system file"),
]

# All text (non-structural) patterns, shared by the `.py` and `.sh` scanners.
_PY_DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    *_PY_PATH_PATTERNS,
    (_PY_SECRET_PATTERN, _SECRET_MATERIAL_REASON),
]

# Precompiled once: these run per line of every `.sh` and per folded string of every
# `.py`, which is the hot path of the whole scan (see the cost note in
# scan_skill_bundle). Measured: compiling here paid for R-D's four extra patterns per
# `.sh` line, so widening the `.sh` rules cost nothing (1382 ms → 1335 ms on 60k lines).
_PY_PATH_RE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), reason) for p, reason in _PY_PATH_PATTERNS
]
_PY_TEXT_RE: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(p, re.IGNORECASE), p, reason) for p, reason in _PY_DESTRUCTIVE_PATTERNS
]
_PY_SECRET_RE = re.compile(_PY_SECRET_PATTERN)
_SKILL_DESTRUCTIVE_RE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), p) for p in _SKILL_DESTRUCTIVE_PATTERNS
]

# Modules whose mere import makes a script network-capable. `subprocess` is treated
# the same way by _scan_py_file: a script that can shell out can curl.
_PY_NET_MODULES = frozenset({
    "aiohttp", "boto3", "botocore", "ftplib", "http", "httpx", "paramiko",
    "requests", "smtplib", "socket", "telnetlib", "urllib", "urllib3",
    "websocket", "websockets", "xmlrpc",
})
# Retained for the Task 5 interface contract and as the module set in regex form.
# NOT the live check any more: _py_imports_network resolves imports through the ast
# bindings instead, which is why a module named only in a comment can no longer arm
# the secret-material rule. Derived, so there is one source of truth.
_PY_NET_PATTERN = r"\b(" + "|".join(sorted(_PY_NET_MODULES)) + r")\b"

_PY_SHELL_ESCAPE_CALLS: dict[tuple[str, ...], str] = {
    ("os", "system"): "shell escape via os.system/os.popen",
    ("os", "popen"): "shell escape via os.system/os.popen",
}
_PY_SUBPROCESS_CALLS = frozenset({
    ("subprocess", name)
    for name in ("run", "call", "check_call", "check_output", "Popen")
})
_PY_DYNAMIC_EXEC_CALLS = frozenset({
    ("eval",), ("exec",), ("builtins", "eval"), ("builtins", "exec"),
})
_PY_RMTREE_CALLS = frozenset({("shutil", "rmtree")})
_PY_JOIN_CALLS = frozenset({("os", "path", "join"), ("posixpath", "join")})
_PY_EXPANDUSER_CALLS = frozenset({("os", "path", "expanduser"), ("Path", "expanduser")})
_PY_HOME_CALLS = frozenset({("pathlib", "Path", "home"), ("Path", "home")})
_PY_PATH_CALLS = frozenset({("pathlib", "Path"), ("Path",), ("pathlib", "PurePath")})

# Folding placeholders. _HOME_MARKER stands for the user's home directory; the
# adjacency that the path patterns need survives either way.
_HOME_MARKER = "<home>"
_UNKNOWN_MARKER = "?"
_DESTRUCTIVE_PATH_TARGETS = frozenset({"/", "/*", _HOME_MARKER, _HOME_MARKER + "/"})

# ast node types _py_fold can turn into a string. Everything else in a module (the
# statements, operators and Load/Store contexts that dominate ast.walk) is skipped
# without attempting a fold.
_PY_FOLDABLE_NODES = (
    ast.Constant, ast.Name, ast.JoinedStr, ast.BinOp, ast.Attribute, ast.Call,
)

# Prefixes scan_skill_safety puts in front of the offending command, which _scan_skill_md
# strips back off to recover the command itself (R-F).
_SKILL_FINDING_PREFIXES = ("destructive command: ", "blocked command: ")


def _finding(rel: str, line: int, snippet: str, reason: str) -> dict:
    return {"file": rel, "line": line, "snippet": snippet[:120],
            "tier": "blocked", "reason": reason}


def _text_lines(text: str) -> list[str]:
    """Split on real line terminators only — never on \\x0c/\\x0b/\\x85/U+2028.

    str.splitlines() treats those as line breaks; neither bash nor CPython does,
    so splitting on them lets `rm\\x0c-rf /` hide from a line-based scan.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _match_text_patterns(text: str) -> tuple[str, str] | None:
    """First (pattern, reason) in _PY_DESTRUCTIVE_PATTERNS matching `text`."""
    for compiled, pattern, reason in _PY_TEXT_RE:
        if compiled.search(text):
            return pattern, reason
    return None


def _scan_sh_file(path: Path, rel: str) -> list[dict]:
    """Line-scan a packaged shell script.

    Three rule classes: the promotion-gate destructive patterns, the shared runtime
    classifier (blocked tier only — 'unknown'/'write' are not findings), and the
    credential-path/secret-material text rules mirrored from the `.py` side. The
    text rules are NOT gated on network capability here: a shell script can always
    shell out, and the sandbox returns stdout to the agent, so stdout alone is an
    exfil channel.
    """
    findings: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(_text_lines(text), 1):
        cmd = raw.strip()
        if not cmd or cmd.startswith("#"):
            continue
        low = cmd.lower()
        hit = next((p for compiled, p in _SKILL_DESTRUCTIVE_RE if compiled.search(low)), None)
        if hit:
            findings.append(_finding(rel, lineno, cmd, f"destructive command (pattern: {hit})"))
            continue
        text_hit = _match_text_patterns(cmd)
        if text_hit:
            findings.append(_finding(rel, lineno, cmd, text_hit[1]))
            continue
        try:
            tier = classify_shell_command(cmd)
        except Exception:
            continue
        if tier == "blocked":
            findings.append(_finding(rel, lineno, cmd, "blocked command"))
    return findings


# ── Python bundle analysis (ast-based) ────────────────────────────


def _py_prepass(tree: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
    """Collect import and assignment nodes in ONE walk.

    Bindings must be complete before constants are folded (`target =
    os.path.expanduser('~')` needs them), and constants must be complete before the
    analysis walk. Partitioning first keeps that ordering while walking the tree
    twice in total instead of four times — the walk itself is the dominant cost on a
    large file, not the rules.
    """
    imports: list[ast.AST] = []
    assigns: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.For,
                              ast.comprehension)):
            assigns.append(node)
    return imports, assigns


def _py_import_bindings(nodes: list[ast.AST]) -> dict[str, tuple[str, ...]]:
    """Map every local name bound by an import to its fully-qualified target.

    This is what makes the call rules resolve by BINDING rather than by `os.`/
    `subprocess.` prefix text, so `import os as o`, `from os import system` and
    `from subprocess import run` all land on the same target.
    """
    bindings: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = tuple(alias.name.split("."))
                if alias.asname:
                    bindings[alias.asname] = target
                else:
                    bindings[alias.name] = target
                    bindings[target[0]] = (target[0],)
        elif isinstance(node, ast.ImportFrom):
            base = tuple(node.module.split(".")) if node.module else ()
            for alias in node.names:
                bindings[alias.asname or alias.name] = base + (alias.name,)
    return bindings


def _py_dotted(node: ast.AST) -> tuple[str, ...] | None:
    """Dotted-name parts of a Name/Attribute chain, or None if not a plain name."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return tuple(reversed(parts))
    return None


def _py_resolve(node: ast.AST, bindings: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    """Resolve a Name/Attribute chain through the import bindings (longest prefix)."""
    parts = _py_dotted(node)
    if parts is None:
        return None
    for i in range(len(parts), 0, -1):
        key = ".".join(parts[:i])
        if key in bindings:
            return bindings[key] + parts[i:]
    return parts


def _py_match_call(target: tuple[str, ...] | None,
                   table, allow_bare: bool = False) -> tuple[str, ...] | None:
    """Match a resolved call target against `table`, exact tuple first.

    Exact membership alone let an attribute chain through a re-exporting module walk
    around every call rule: `shutil.os.system`, `os.path.os.system`,
    `subprocess.os.popen` all resolve to a 3-tuple, and the dependency-injection idiom
    (`self.os = os` then `self.os.system(c)`) resolves to `("self","os","system")`.
    Matching the trailing TWO segments closes all of them while still requiring the
    module name, so a method merely called `system` cannot match.

    `allow_bare` additionally matches a trailing SINGLE segment, and is used only for
    the dynamic-exec names, where the pre-ast scan was equally broad (`\\b(eval|exec)\\s*\\(`
    matched `obj.eval(...)` too). The cost is that a method named `eval`/`exec` reached
    through a plain name is flagged — fail-closed, and identical to the old behaviour.
    """
    if target is None:
        return None
    if target in table:
        return target
    if len(target) > 2 and target[-2:] in table:
        return target[-2:]
    if allow_bare and len(target) > 1 and target[-1:] in table:
        return target[-1:]
    return None


def _py_shell_true(value: ast.AST) -> bool:
    """Whether a ``shell=`` keyword value is, or contains, a constant ``True``.

    A constant decides itself; any other expression counts only if a constant `True`
    appears in its subtree, which closes `shell=True if sys.platform else False`.
    Deliberately NOT "anything that is not False" — `shell=use_shell` is legitimate
    code and stays parked (see KNOWN LIMITATIONS).
    """
    if isinstance(value, ast.Constant):
        return value.value is True
    return any(isinstance(n, ast.Constant) and n.value is True for n in ast.walk(value))


def _py_const_strings(nodes: list[ast.AST],
                      bindings: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Names assigned a foldable string exactly once, anywhere in the module.

    Single assignment only: a name written twice is ambiguous and is dropped, so
    `target = '/'` folds but a reassigned variable does not.
    """
    candidates: dict[str, ast.expr] = {}
    rebound: set[str] = set()

    def _record(name: str, value: ast.expr) -> None:
        if name in candidates or name in rebound:
            rebound.add(name)
            candidates.pop(name, None)
            return
        candidates[name] = value

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _record(target.id, node.value)
                else:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            rebound.add(sub.id)
                            candidates.pop(sub.id, None)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                _record(node.target.id, node.value)
        elif isinstance(node, (ast.AugAssign, ast.For, ast.comprehension)):
            target = getattr(node, "target", None)
            if target is not None:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        rebound.add(sub.id)
                        candidates.pop(sub.id, None)

    consts: dict[str, str] = {}
    for name, value in candidates.items():
        folded = _py_fold(value, {}, bindings)
        if folded is not None:
            consts[name] = folded
    return consts


def _py_fold(node: ast.AST, consts: dict[str, str],
             bindings: dict[str, tuple[str, ...]]) -> str | None:
    """Constant-fold a string-valued expression, or None.

    Handles literals and implicit/explicit concatenation, f-strings, `os.path.join`,
    `Path(...) / '...'`, `expanduser('~')`, `Path.home()`, `pwd.getpwuid(...).pw_dir`
    and single-assignment local constants. Unfoldable components become
    _UNKNOWN_MARKER so the path patterns' adjacency requirement still holds — the
    point is that `os.path.join(home, '.aws', 'credentials')` must not defeat a rule
    that the equivalent literal triggers.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            # open() accepts bytes paths, so b'/etc/shadow' is ordinary Python and the
            # path rules must see its text (fix round 2, R1).
            return node.value.decode("utf-8", "replace")
        return None
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append(_UNKNOWN_MARKER)
        return "".join(parts)
    if isinstance(node, ast.BinOp):
        left = _py_fold(node.left, consts, bindings)
        right = _py_fold(node.right, consts, bindings)
        if isinstance(node.op, ast.Add) and left is not None and right is not None:
            return left + right
        if isinstance(node.op, ast.Div) and right is not None:
            return (left if left is not None else _UNKNOWN_MARKER).rstrip("/") + "/" + right
        return None
    if isinstance(node, ast.Attribute):
        # pwd.getpwuid(os.getuid()).pw_dir — the home directory
        if node.attr == "pw_dir":
            return _HOME_MARKER
        return None
    if isinstance(node, ast.Call):
        target = _py_resolve(node.func, bindings)
        if target is None:
            return None
        if target in _PY_HOME_CALLS:
            return _HOME_MARKER
        if target in _PY_JOIN_CALLS:
            folded = [_py_fold(a, consts, bindings) or _UNKNOWN_MARKER for a in node.args]
            return "/".join(folded) if folded else None
        if target in _PY_EXPANDUSER_CALLS:
            inner = _py_fold(node.args[0], consts, bindings) if node.args else None
            if inner is None:
                return _HOME_MARKER
            return _HOME_MARKER + inner[1:] if inner.startswith("~") else inner
        if target in _PY_PATH_CALLS:
            folded = [_py_fold(a, consts, bindings) or _UNKNOWN_MARKER for a in node.args]
            return "/".join(folded) if folded else None
        if target[-1:] == ("expanduser",) or target[-1:] == ("resolve",) or target[-1:] == ("absolute",):
            # method form: <foldable>.expanduser() / .resolve() — pass the receiver through
            receiver = getattr(node.func, "value", None)
            if receiver is not None:
                inner = _py_fold(receiver, consts, bindings)
                if inner is not None:
                    return _HOME_MARKER + inner[1:] if inner.startswith("~") else inner
        return None
    return None


def _py_fold_argv(node: ast.AST | None, consts: dict[str, str],
                  bindings: dict[str, tuple[str, ...]]) -> str | None:
    """Fold a subprocess first argument (argv list or command string) to one string."""
    if node is None:
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        parts = [_py_fold(e, consts, bindings) or _UNKNOWN_MARKER for e in node.elts]
        return " ".join(parts) if parts else None
    return _py_fold(node, consts, bindings)


def _py_imports_network(bindings: dict[str, tuple[str, ...]]) -> bool:
    """Whether the module imports something that can reach the network.

    Import-based, which is why a module merely named in a comment can no longer arm
    the secret-material rule. `subprocess` counts: a script that can shell out can
    curl. The call-based half (os.system/os.popen/subprocess.*) is picked up during
    the main walk in _scan_py_file rather than in a second pass over the tree.
    """
    return any(
        target and (target[0] in _PY_NET_MODULES or target[0] == "subprocess")
        for target in bindings.values()
    )


def _py_snippet(text: str, lines: list[str], node: ast.AST) -> str:
    """One-line snippet for a node — source segment if available, else its line."""
    segment = None
    try:
        segment = ast.get_source_segment(text, node)
    except Exception:
        segment = None
    if not segment:
        lineno = getattr(node, "lineno", 0)
        segment = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
    return " ".join(segment.split())


def _scan_py_file(path: Path, rel: str) -> list[dict]:
    """Structurally scan a packaged Python file.

    A file that does not parse is a finding, not a pass: the gate must not let
    through code it cannot analyse.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except Exception as e:
        return [_finding(rel, 0, "", f"unparseable python: {e}")]

    lines = _text_lines(text)
    imports, assigns = _py_prepass(tree)
    bindings = _py_import_bindings(imports)
    consts = _py_const_strings(assigns, bindings)
    # Import half now; the call half (shell escape / subprocess) is set in the walk
    # below, so the tree is walked once instead of twice.
    has_net = _py_imports_network(bindings)

    findings: list[dict] = []
    seen: set[tuple[int, str]] = set()

    def add(node: ast.AST, reason: str, snippet: str | None = None) -> None:
        lineno = getattr(node, "lineno", 0)
        if (lineno, reason) in seen:
            return
        seen.add((lineno, reason))
        findings.append(_finding(rel, lineno, snippet if snippet is not None
                                 else _py_snippet(text, lines, node), reason))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _py_resolve(node.func, bindings)
            escape = _py_match_call(target, _PY_SHELL_ESCAPE_CALLS)
            if escape is not None:
                add(node, _PY_SHELL_ESCAPE_CALLS[escape])
                has_net = True
            elif _py_match_call(target, _PY_DYNAMIC_EXEC_CALLS, allow_bare=True):
                add(node, "dynamic code execution")
            elif _py_match_call(target, _PY_RMTREE_CALLS):
                folded = _py_fold(node.args[0], consts, bindings) if node.args else None
                if folded is not None and folded.strip() in _DESTRUCTIVE_PATH_TARGETS:
                    add(node, "rmtree on filesystem root or home")
            elif _py_match_call(target, _PY_SUBPROCESS_CALLS):
                has_net = True
                if any(kw.arg == "shell" and _py_shell_true(kw.value)
                       for kw in node.keywords):
                    add(node, "subprocess with shell=True")
                argv = _py_fold_argv(node.args[0] if node.args else None, consts, bindings)
                if argv:
                    low = argv.lower()
                    hit = next((p for compiled, p in _SKILL_DESTRUCTIVE_RE
                                if compiled.search(low)), None)
                    if hit:
                        add(node, f"destructive command in subprocess argv (pattern: {hit})", argv)
        elif not isinstance(node, _PY_FOLDABLE_NODES):
            # Nothing else can fold to a string, so skip the fold attempt entirely —
            # most nodes in a real module are statements, operators and Load/Store ctx.
            continue

        folded = _py_fold(node, consts, bindings)
        if folded:
            for compiled, reason in _PY_PATH_RE:
                if compiled.search(folded):
                    add(node, reason, folded)
                    break

    # Secret-material mentions are a name rule, not a path rule, so they stay a raw
    # text match (identifiers as well as string keys) — and only matter when the file
    # can also reach the network or shell out.
    if has_net:
        for lineno, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if _PY_SECRET_RE.search(line) and (lineno, _SECRET_MATERIAL_REASON) not in seen:
                seen.add((lineno, _SECRET_MATERIAL_REASON))
                findings.append(_finding(rel, lineno, line, _SECRET_MATERIAL_REASON))

    findings.sort(key=lambda f: (f["line"], f["reason"]))
    return findings


# ── Bundle entry point ────────────────────────────────────────────


def _fenced_line_numbers(body_lines: list[str]) -> set[int]:
    """1-based body line numbers that sit inside a ``` fenced block."""
    inside = False
    fenced: set[int] = set()
    for i, raw in enumerate(body_lines, 1):
        if raw.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            fenced.add(i)
    return fenced


def _scan_skill_md(pkg_dir: Path) -> list[dict]:
    """Scan pkg_dir/SKILL.md's prose, recovering a real file line per finding."""
    from agenticops.skills.loader import parse_frontmatter

    skill_md = pkg_dir / "SKILL.md"
    try:
        # is_file() belongs INSIDE the try: it only swallows ENOENT/ENOTDIR/EBADF/ELOOP,
        # so a pkg_dir that is not searchable raises EACCES here — and scan_skill_bundle
        # promises never to raise (fix round 2, Q3a).
        if not skill_md.is_file():
            return []
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        _, body = parse_frontmatter(content)
        body_lines = _text_lines(body)
        fenced = _fenced_line_numbers(body_lines)
        # SKILL.md line numbers must be FILE-relative, so add back the frontmatter.
        offset = content[: len(content) - len(body)].count("\n")
        findings: list[dict] = []
        for text in scan_skill_safety(body)["findings"]:
            command = next((text[len(p):] for p in _SKILL_FINDING_PREFIXES
                            if text.startswith(p)), "")
            line = 0
            if command:
                hits = [i for i, raw in enumerate(body_lines, 1) if command in raw]
                # Prose quoting the command must not win the line number over the fence
                # that actually runs it (fix round 2, R-F).
                line = next((i for i in hits if i in fenced), hits[0] if hits else 0)
            findings.append(_finding("SKILL.md", offset + line if line else 0,
                                     command, text))
        return findings
    except Exception as e:
        return [_finding("SKILL.md", 0, "", f"unreadable SKILL.md: {e}")]


def scan_skill_bundle(pkg_dir: Path) -> dict:
    """Scan a whole skill package — SKILL.md prose plus every packaged .sh/.py.

    Returns ``{"safe": bool, "findings": [{"file","line","snippet","tier","reason"}]}``
    and never raises: a bad path type, a missing directory, an unreadable file and an
    unreadable subdirectory all come back as ``safe=False`` findings. "Nothing found"
    and "nowhere to look" must never be the same answer for a promote gate.

    Scope:

    * Only ``pkg_dir/SKILL.md`` is scanned as prose. A **nested** ``SKILL.md`` is
      treated like any other ``.md`` payload and is NOT scanned. That is deliberate:
      the boundary for prose is the execution-time command classifier, which
      re-classifies every command a skill actually runs.
    * Non-executable payloads (``.md``/``.txt``/``.json``/``.yaml``/``.csv`` other
      than ``pkg_dir/SKILL.md``) are not scanned.
    * Symlinks are reported and never followed, so a package cannot pull a payload
      in from outside itself.
    * ``.py`` is analysed with ``ast`` (structural); ``.sh`` is line-scanned.

    ``tier`` is always ``"blocked"`` today. See the KNOWN LIMITATIONS block above
    this section for what the scan deliberately does not catch — notably obfuscation
    and write-then-execute — and for the rule that must be honoured if a lower tier
    is ever emitted.

    Cost is per-payload-size and this runs synchronously inside promote. Measured on
    this machine: ~1.3 s for a 1.8 MiB ``.sh`` (unchanged by the rewrite) and ~1.4 s
    for a 1.5 MiB ``.py`` — the ``ast`` rewrite made the ``.py`` side ~10x SLOWER than
    the regex scan it replaced (``ast.walk`` dominates), which is the price of closing
    the idiom-based evasions. Worst case at the 2 MiB import cap is ~2 s per file.
    """
    try:
        pkg_dir = Path(pkg_dir)
    except TypeError as e:
        return {"safe": False, "findings": [
            _finding(str(pkg_dir), 0, "", f"invalid package path: {e}")]}
    if not pkg_dir.is_dir():
        return {"safe": False, "findings": [
            _finding(str(pkg_dir), 0, "", "package path is missing or not a directory")]}

    findings: list[dict] = _scan_skill_md(pkg_dir)

    def _rel(target: object) -> str:
        try:
            return str(Path(str(target)).relative_to(pkg_dir))
        except (TypeError, ValueError):
            return str(target)

    def _onerror(err: OSError) -> None:
        # os.walk swallows per-directory errors unless we observe them here; a
        # directory the scan cannot enter must be a finding, never a silent skip.
        findings.append(_finding(_rel(getattr(err, "filename", None) or pkg_dir), 0, "",
                                 f"unreadable directory: {err}"))

    for dirpath, dirnames, filenames in os.walk(pkg_dir, onerror=_onerror, followlinks=False):
        base = Path(dirpath)
        dirnames.sort()
        for name in list(dirnames):
            if (base / name).is_symlink():
                findings.append(_finding(_rel(base / name), 0, "", "symlink in package"))
                dirnames.remove(name)
        for name in sorted(filenames):
            path = base / name
            rel = _rel(path)
            if path.is_symlink():
                findings.append(_finding(rel, 0, "", "symlink in package"))
                continue
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            try:
                if suffix == ".sh":
                    findings.extend(_scan_sh_file(path, rel))
                elif suffix == ".py":
                    findings.extend(_scan_py_file(path, rel))
            except Exception as e:
                findings.append(_finding(rel, 0, "", f"unreadable script: {e}"))

    return {"safe": len(findings) == 0, "findings": findings}
