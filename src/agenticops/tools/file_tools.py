"""Local file tools — read files, list directories, search file contents, and write files.

Provides agents with the ability to inspect and write local files such as
configuration, logs, application code, Terraform/CloudFormation templates,
Kubernetes manifests, and other operational artifacts.

Security: a blocklist prevents access to sensitive paths (credentials, private
keys, secrets, etc.). Admin mode (AIOPS_FILE_TOOLS_ADMIN_MODE=true) unlocks
cluster management paths (~/.ssh, ~/.aws, ~/.kube) while keeping system-level
blocks (/etc/shadow etc.) in place.

Output is truncated to prevent agent context overflow.
"""

from __future__ import annotations

import glob as _glob
import logging
import os
from pathlib import Path

from strands import tool

from agenticops.config import settings

logger = logging.getLogger(__name__)

# ── Output limits (matches metadata_tools.py / aws_cli_tool.py) ────────
MAX_RESULT_CHARS = 4000
MAX_LIST_RESULT_CHARS = 6000
MAX_WRITE_BYTES = 1_048_576  # 1 MB


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated — file too large, use offset/limit or tail)"


# ── Security blocklists ─────────────────────────────────────────────────

# Admin paths — blocked by default, unlocked by AIOPS_FILE_TOOLS_ADMIN_MODE=true.
# These are needed for cluster management (SSH configs, AWS profiles, kubeconfig).
_ADMIN_PATH_SUBSTRINGS = (
    "/.ssh/",
    "/.aws/credentials",
    "/.aws/config",
    "/.kube/config",
)

# Admin filenames — private keys used for SSH.
_ADMIN_FILENAMES = frozenset({
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
})

# Admin extensions — key files needed for SSH/TLS.
_ADMIN_EXTENSIONS = frozenset({
    ".pem", ".key",
})

# Always blocked — system-level secrets, never exposed regardless of mode.
_SYSTEM_PATH_SUBSTRINGS = (
    "/.gnupg/",
    "/.docker/config.json",
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/sudoers",
    "/private/etc/shadow",
)

# Always blocked extensions — crypto keystores/certs (not SSH keys).
_SYSTEM_EXTENSIONS = frozenset({
    ".p12", ".pfx", ".jks",
    ".keystore", ".gpg", ".asc",
})

# Always blocked filenames — application secrets.
_SYSTEM_FILENAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.staging",
    "credentials", "credentials.json", "credentials.yaml",
    "secrets.yaml", "secrets.json", "secrets.yml",
    "service-account.json", "token", "master.key",
})


def _is_blocked(path: str) -> str | None:
    """Return a reason string if the path is blocked, or None if safe."""
    try:
        resolved = str(Path(path).resolve())
    except (OSError, ValueError):
        return "Invalid path"

    admin_mode = settings.file_tools_admin_mode
    lower = resolved.lower()

    # System-level paths — always blocked
    for pattern in _SYSTEM_PATH_SUBSTRINGS:
        if pattern.lower() in lower:
            return f"Blocked: path contains '{pattern}'"

    # Admin paths — blocked unless admin mode is on
    if not admin_mode:
        for pattern in _ADMIN_PATH_SUBSTRINGS:
            if pattern.lower() in lower:
                return f"Blocked: path contains '{pattern}' (set AIOPS_FILE_TOOLS_ADMIN_MODE=true to allow)"

    basename = os.path.basename(resolved).lower()

    # System filenames — always blocked
    if basename in _SYSTEM_FILENAMES:
        return f"Blocked: filename '{basename}' is in the sensitive-file blocklist"

    # Admin filenames — blocked unless admin mode
    if not admin_mode and basename in _ADMIN_FILENAMES:
        return f"Blocked: filename '{basename}' (set AIOPS_FILE_TOOLS_ADMIN_MODE=true to allow)"

    _, ext = os.path.splitext(basename)
    ext_lower = ext.lower()

    # System extensions — always blocked
    if ext_lower in _SYSTEM_EXTENSIONS:
        return f"Blocked: extension '{ext}' is in the sensitive-file blocklist"

    # Admin extensions — blocked unless admin mode
    if not admin_mode and ext_lower in _ADMIN_EXTENSIONS:
        return f"Blocked: extension '{ext}' (set AIOPS_FILE_TOOLS_ADMIN_MODE=true to allow)"

    return None


# ── @tool functions ─────────────────────────────────────────────────────


@tool
def read_local_file(
    path: str,
    offset: int = 0,
    limit: int = 200,
    encoding: str = "utf-8",
) -> str:
    """Read a local file and return its contents with line numbers.

    Use this to inspect configuration files, log files, application code,
    Terraform/CloudFormation templates, Kubernetes manifests, systemd unit
    files, nginx/apache configs, Dockerfiles, scripts, and other operational
    artifacts on the local filesystem.

    Args:
        path: Absolute or relative file path to read.
        offset: Line number to start reading from (0-based, default 0).
        limit: Maximum number of lines to return (default 200).
        encoding: File encoding (default utf-8).

    Returns:
        File contents with line numbers, or error message.
    """
    blocked = _is_blocked(path)
    if blocked:
        return f"ACCESS DENIED: {blocked}. Cannot read sensitive files."

    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"File not found: {path}"
        if not resolved.is_file():
            return f"Not a file: {path} (use list_local_directory for directories)"
        if resolved.stat().st_size > 10 * 1024 * 1024:  # 10 MB
            return f"File too large ({resolved.stat().st_size:,} bytes). Use tail_local_file for large files."

        with open(resolved, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        selected = lines[offset: offset + limit]

        output_lines = []
        for i, line in enumerate(selected, start=offset + 1):
            output_lines.append(f"{i:>6}\t{line.rstrip()}")

        header = f"# {resolved} ({total} lines total, showing {offset+1}-{offset+len(selected)})\n"
        content = header + "\n".join(output_lines)
        return _truncate(content)

    except UnicodeDecodeError:
        return f"Cannot read {path}: binary file (not text). Try encoding='latin-1' for raw bytes."
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


@tool
def tail_local_file(path: str, lines: int = 100, encoding: str = "utf-8") -> str:
    """Read the last N lines of a file (useful for log files).

    Args:
        path: Absolute or relative file path.
        lines: Number of lines from the end to return (default 100).
        encoding: File encoding (default utf-8).

    Returns:
        Last N lines of the file with line numbers.
    """
    blocked = _is_blocked(path)
    if blocked:
        return f"ACCESS DENIED: {blocked}. Cannot read sensitive files."

    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"File not found: {path}"
        if not resolved.is_file():
            return f"Not a file: {path}"

        with open(resolved, "r", encoding=encoding, errors="replace") as f:
            all_lines = f.readlines()

        total = len(all_lines)
        start = max(0, total - lines)
        selected = all_lines[start:]

        output_lines = []
        for i, line in enumerate(selected, start=start + 1):
            output_lines.append(f"{i:>6}\t{line.rstrip()}")

        header = f"# {resolved} (last {len(selected)} of {total} lines)\n"
        content = header + "\n".join(output_lines)
        return _truncate(content)

    except Exception as e:
        return f"Error reading {path}: {e}"


@tool
def search_local_file(path: str, pattern: str, max_matches: int = 30) -> str:
    """Search a file for lines matching a pattern (case-insensitive substring match).

    Use this to find specific configuration entries, error patterns, or
    keywords in large files without reading the entire file.

    Args:
        path: Absolute or relative file path to search.
        pattern: Text pattern to search for (case-insensitive).
        max_matches: Maximum number of matching lines to return (default 30).

    Returns:
        Matching lines with line numbers and context.
    """
    blocked = _is_blocked(path)
    if blocked:
        return f"ACCESS DENIED: {blocked}. Cannot read sensitive files."

    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"File not found: {path}"
        if not resolved.is_file():
            return f"Not a file: {path}"

        pattern_lower = pattern.lower()
        matches = []

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                if pattern_lower in line.lower():
                    matches.append(f"{i:>6}\t{line.rstrip()}")
                    if len(matches) >= max_matches:
                        break

        if not matches:
            return f"No matches for '{pattern}' in {resolved}"

        header = f"# {resolved} — {len(matches)} matches for '{pattern}'\n"
        content = header + "\n".join(matches)
        return _truncate(content, MAX_LIST_RESULT_CHARS)

    except Exception as e:
        return f"Error searching {path}: {e}"


@tool
def list_local_directory(path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
    """List files in a local directory with optional glob pattern filtering.

    Use this to discover configuration files, log files, scripts, and other
    artifacts in a directory tree.

    Args:
        path: Directory path to list (default: current directory).
        pattern: Glob pattern to filter files (e.g., '*.conf', '*.yaml', '*.log').
        recursive: If True, search subdirectories recursively (default False).

    Returns:
        List of files with sizes, or error message.
    """
    blocked = _is_blocked(path)
    if blocked:
        return f"ACCESS DENIED: {blocked}."

    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"Directory not found: {path}"
        if not resolved.is_dir():
            return f"Not a directory: {path}"

        if recursive:
            glob_pattern = f"**/{pattern}"
        else:
            glob_pattern = pattern

        entries = sorted(resolved.glob(glob_pattern))[:200]  # cap at 200

        output_lines = []
        for entry in entries:
            if entry.is_file():
                size = entry.stat().st_size
                if size >= 1024 * 1024:
                    size_str = f"{size / 1024 / 1024:.1f}M"
                elif size >= 1024:
                    size_str = f"{size / 1024:.1f}K"
                else:
                    size_str = f"{size}B"
                output_lines.append(f"  {size_str:>8}  {entry.relative_to(resolved)}")
            elif entry.is_dir():
                output_lines.append(f"     dir/  {entry.relative_to(resolved)}/")

        if not output_lines:
            return f"No files matching '{pattern}' in {resolved}"

        header = f"# {resolved} ({len(output_lines)} entries, pattern='{pattern}')\n"
        content = header + "\n".join(output_lines)
        return _truncate(content, MAX_LIST_RESULT_CHARS)

    except Exception as e:
        return f"Error listing {path}: {e}"


@tool
def file_stat(path: str) -> str:
    """Get file metadata: size, modification time, permissions, type.

    Args:
        path: Absolute or relative file path.

    Returns:
        File metadata as formatted text.
    """
    try:
        resolved = Path(path).resolve()
        if not resolved.exists():
            return f"Not found: {path}"

        stat = resolved.stat()
        import time

        return (
            f"Path: {resolved}\n"
            f"Type: {'file' if resolved.is_file() else 'directory' if resolved.is_dir() else 'other'}\n"
            f"Size: {stat.st_size:,} bytes ({stat.st_size / 1024:.1f} KB)\n"
            f"Modified: {time.ctime(stat.st_mtime)}\n"
            f"Permissions: {oct(stat.st_mode)[-3:]}\n"
            f"Owner UID: {stat.st_uid}\n"
        )
    except Exception as e:
        return f"Error: {e}"


@tool
def write_local_file(path: str, content: str, mode: str = "overwrite") -> str:
    """Write text content to a local file.

    Use this to save analysis results, reports, config snippets, scripts,
    and other operational artifacts to the local filesystem.

    Args:
        path: Absolute or relative file path to write.
        content: Text content to write to the file.
        mode: Write mode — "overwrite" (default) replaces the file,
              "append" adds to the end.

    Returns:
        Confirmation with resolved path and bytes written, or error message.
    """
    blocked = _is_blocked(path)
    if blocked:
        return f"ACCESS DENIED: {blocked}. Cannot write to sensitive files."

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_WRITE_BYTES:
        return (
            f"Content too large: {len(content_bytes):,} bytes "
            f"(limit {MAX_WRITE_BYTES:,} bytes / 1 MB)."
        )

    if mode not in ("overwrite", "append"):
        return f"Invalid mode '{mode}'. Use 'overwrite' or 'append'."

    try:
        resolved = Path(path).resolve()

        # Auto-create parent directories
        resolved.parent.mkdir(parents=True, exist_ok=True)

        file_mode = "w" if mode == "overwrite" else "a"
        with open(resolved, file_mode, encoding="utf-8") as f:
            f.write(content)

        action = "Wrote" if mode == "overwrite" else "Appended"
        return f"{action} {len(content_bytes):,} bytes to {resolved}"

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"
