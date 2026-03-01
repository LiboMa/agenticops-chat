"""Security classification for shell and kubectl commands.

Three-tier model mirroring src/agenticops/tools/aws_cli_tool.py:
- readonly: Safe diagnostic/inspection commands (auto-execute)
- write: Commands that modify state (require confirmation)
- blocked: Dangerous/destructive commands (rejected outright)

Unknown commands default to 'write' (require confirmation).
"""

from __future__ import annotations

import re

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
    r"rm\s+-rf\s+--no-preserve-root",
    "mkfs",
    r"dd\s+if=",
    "shutdown", "reboot", "poweroff", "halt", "init 0", "init 6",
    "passwd",
    r"curl.*\|\s*bash",
    r"curl.*\|\s*sh",
    r"wget.*\|\s*bash",
    r"wget.*\|\s*sh",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r">\s*/dev/sd",
    r">\s*/dev/null\s*2>&1\s*<\s*/dev/null",
    "format c:",
    r"chmod\s+-R\s+777\s+/\s*$",
    r"chown\s+-R.*\s+/\s*$",
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

    # Check readonly commands
    for ro_cmd in SHELL_READONLY_COMMANDS:
        if cmd_lower == ro_cmd or cmd_lower.startswith(ro_cmd + " "):
            return "readonly"

    # Check write commands
    for wr_cmd in SHELL_WRITE_COMMANDS:
        if cmd_lower == wr_cmd or cmd_lower.startswith(wr_cmd + " "):
            return "write"

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
    r"delete\s+--all\s+-A",
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
