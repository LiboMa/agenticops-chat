"""Security classification for shell and kubectl commands.

Three-tier model mirroring src/agenticops/tools/aws_cli_tool.py:
- readonly: Safe diagnostic/inspection commands (auto-execute)
- write: Commands that modify state (require confirmation)
- blocked: Dangerous/destructive commands (rejected outright)

Unknown commands default to 'write' (require confirmation).
"""

from __future__ import annotations

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

# Deterministic, zero-LLM patterns for packaged Python. Auxiliary gate only —
# the real boundary is the sandbox (no credentials, no network) plus human
# approval. Obfuscated code is explicitly out of scope.
_PY_DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    (r"shutil\.rmtree\s*\(\s*[\"']/[\"']", "rmtree on filesystem root"),
    (r"\bos\.(system|popen)\s*\(", "shell escape via os.system/os.popen"),
    (r"subprocess\.(run|call|Popen|check_output)\s*\(.*shell\s*=\s*True", "subprocess with shell=True"),
    (r"\.aws[/\\](credentials|config)", "reads a cloud credential file"),
    (r"\.ssh[/\\]id_[a-z0-9_]+", "reads an SSH private key"),
    (r"/etc/(shadow|sudoers)", "reads a privileged system file"),
    (r"AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN", "references cloud secret material"),
    (r"\b(eval|exec)\s*\(", "dynamic code execution"),
]
_PY_NET_PATTERN = r"\b(requests|urllib|urllib3|httpx|aiohttp|socket|boto3|botocore)\b"
_SECRET_MATERIAL_REASON = "references cloud secret material"


def _scan_sh_file(path: Path, rel: str) -> list[dict]:
    findings: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), 1):
        cmd = raw.strip()
        if not cmd or cmd.startswith("#"):
            continue
        low = cmd.lower()
        hit = next((p for p in _SKILL_DESTRUCTIVE_PATTERNS if re.search(p, low)), None)
        if hit:
            findings.append({"file": rel, "line": lineno, "snippet": cmd[:120],
                             "tier": "blocked", "reason": "destructive command"})
            continue
        try:
            tier = classify_shell_command(cmd)
        except Exception:
            continue
        if tier == "blocked":
            findings.append({"file": rel, "line": lineno, "snippet": cmd[:120],
                             "tier": "blocked", "reason": "blocked command"})
    return findings


def _scan_py_file(path: Path, rel: str) -> list[dict]:
    findings: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    has_net = re.search(_PY_NET_PATTERN, text) is not None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for pattern, reason in _PY_DESTRUCTIVE_PATTERNS:
            if not re.search(pattern, line):
                continue
            # Secret-material mentions only matter when the file can also reach the network.
            if reason == _SECRET_MATERIAL_REASON and not has_net:
                continue
            findings.append({"file": rel, "line": lineno, "snippet": line[:120],
                             "tier": "blocked", "reason": reason})
            break
    return findings


def scan_skill_bundle(pkg_dir: Path) -> dict:
    """Scan a whole skill package — SKILL.md body plus every packaged .sh/.py.

    Returns {"safe": bool, "findings": [{"file","line","snippet","tier","reason"}]}.
    Non-executable payloads (.md/.txt/.json/.yaml/.csv other than SKILL.md) are
    not scanned. Unreadable files are reported as findings, never silently passed.
    """
    from agenticops.skills.loader import parse_frontmatter

    findings: list[dict] = []
    skill_md = pkg_dir / "SKILL.md"
    if skill_md.is_file():
        try:
            _, body = parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            for text in scan_skill_safety(body)["findings"]:
                findings.append({"file": "SKILL.md", "line": 0, "snippet": text[:120],
                                 "tier": "blocked", "reason": text})
        except Exception as e:
            findings.append({"file": "SKILL.md", "line": 0, "snippet": "",
                             "tier": "blocked", "reason": f"unreadable SKILL.md: {e}"})

    for path in sorted(pkg_dir.rglob("*")):
        if path.is_symlink():
            findings.append({"file": str(path.relative_to(pkg_dir)), "line": 0, "snippet": "",
                             "tier": "blocked", "reason": "symlink in package"})
            continue
        if not path.is_file():
            continue
        rel = str(path.relative_to(pkg_dir))
        suffix = path.suffix.lower()
        try:
            if suffix == ".sh":
                findings.extend(_scan_sh_file(path, rel))
            elif suffix == ".py":
                findings.extend(_scan_py_file(path, rel))
        except Exception as e:
            findings.append({"file": rel, "line": 0, "snippet": "",
                             "tier": "blocked", "reason": f"unreadable script: {e}"})

    return {"safe": len(findings) == 0, "findings": findings}
