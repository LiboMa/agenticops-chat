"""Skill ingestion from wide sources — URL / git repo / zip archive.

Human-driven only: agents get no import tool. Every imported package lands as
a DRAFT (never published, never injected into a prompt, never executed), so the
existing draft -> review -> promote -> .archive chain stays the single approval
path. Nothing inside an imported package is ever run during import.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from agenticops.config import settings
from agenticops.skills.curator import _write_skill_md
from agenticops.skills.loader import (
    _invalidate_skills_cache,
    _validate_skill_name,
    normalize_skill_frontmatter,
    parse_frontmatter,
)

logger = logging.getLogger(__name__)

# Directories never treated as (or searched for) skill packages.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".archive", ".staging", "draft"}


def discover_packages(root: Path) -> list[Path]:
    """Recursively find every directory holding a SKILL.md.

    A directory that has SKILL.md IS a package and is not descended into (so a
    skill's own references/SKILL.md never becomes a second package). Skips VCS,
    vendor and dot directories. Deterministic (sorted) output.
    """
    found: list[Path] = []

    def walk(d: Path) -> None:
        if (d / "SKILL.md").is_file():
            found.append(d)
            return
        try:
            children = sorted(d.iterdir())
        except OSError as e:
            logger.warning("Cannot list %s during skill discovery: %s", d, e)
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            walk(child)

    if root.is_dir():
        walk(root)
    return sorted(found)


@dataclass
class ImportedSkill:
    name: str
    path: Path
    files: int
    bytes: int


@dataclass
class ImportResult:
    source_uri: str
    source_ref: str
    installed: list[ImportedSkill] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


class _Reject(Exception):
    """A package failed validation — record it and move to the next one."""


def _package_files(pkg_dir: Path) -> list[Path]:
    """Every regular file in the package. Rejects symlinks, specials, escapes."""
    root = pkg_dir.resolve()
    out: list[Path] = []
    for p in sorted(pkg_dir.rglob("*")):
        rel = p.relative_to(pkg_dir)
        if p.is_symlink():
            raise _Reject(f"symlink not allowed: {rel}")
        if p.is_dir():
            continue
        if not p.is_file():
            raise _Reject(f"not a regular file: {rel}")
        if not str(p.resolve()).startswith(str(root) + os.sep):
            raise _Reject(f"path escapes package root: {rel}")
        # A hard link is a regular file inside the root, yet its bytes belong to
        # some other file on the host — copying it would exfiltrate that content.
        if p.stat().st_nlink > 1:
            raise _Reject(f"hard link not allowed: {rel}")
        out.append(p)
    return out


def _validate_package(pkg_dir: Path) -> list[Path]:
    files = _package_files(pkg_dir)
    max_files = settings.skills_import_max_files
    if len(files) > max_files:
        raise _Reject(f"too many files: {len(files)} > {max_files}")
    cap = settings.skills_import_max_package_bytes
    total = sum(f.stat().st_size for f in files)
    if total > cap:
        raise _Reject(f"package too large: {total} > {cap} bytes")
    allowed = {e.lower() for e in settings.skills_import_allowed_extensions}
    for f in files:
        if f.suffix.lower() not in allowed:
            raise _Reject(f"file type not allowed: {f.relative_to(pkg_dir)}")
    return files


def _stamp_provenance(pkg_dir: Path, name: str, source_uri: str, source_ref: str) -> None:
    """Rewrite SKILL.md frontmatter with import provenance (created_by=imported)."""
    fm, body = parse_frontmatter((pkg_dir / "SKILL.md").read_text(encoding="utf-8"))
    fm = normalize_skill_frontmatter(fm)
    fm["name"] = name
    fm["created_by"] = "imported"
    fm["status"] = "active"
    fm["source_uri"] = source_uri
    fm["source_ref"] = source_ref
    fm["imported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_skill_md(pkg_dir, fm, body)


def _install_one(pkg_dir: Path, name: str, source_uri: str, source_ref: str) -> ImportedSkill:
    """Copy a validated package into skills_draft_dir/<name> atomically."""
    files = _validate_package(pkg_dir)
    staging_root = settings.skills_draft_dir / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = staging_root / f"{name}-{uuid.uuid4().hex[:8]}"
    try:
        total = 0
        for f in files:
            dst = staging / f.relative_to(pkg_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = f.read_bytes()
            dst.write_bytes(data)
            os.chmod(dst, 0o644)          # never executable — the sandbox names the interpreter
            total += len(data)
        _stamp_provenance(staging, name, source_uri, source_ref)
        target = settings.skills_draft_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)       # atomic — no half-installed state
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return ImportedSkill(name=name, path=target, files=len(files), bytes=total)


def install_packages(
    pkgs: list[Path],
    source_uri: str,
    source_ref: str,
    names: list[str] | None = None,
) -> ImportResult:
    """Install discovered packages as DRAFTS. Per-package fail-soft, security fail-closed."""
    result = ImportResult(source_uri=source_uri, source_ref=source_ref)
    wanted = set(names) if names else None

    for pkg in pkgs:
        try:
            fm, _ = parse_frontmatter((pkg / "SKILL.md").read_text(encoding="utf-8"))
        except Exception as e:
            result.rejected.append((str(pkg), f"unreadable SKILL.md: {e}"))
            continue

        raw_name = (fm.get("name") if isinstance(fm, dict) else None) or pkg.name
        name = str(raw_name).strip()
        # R2: validate against the DESTINATION dir — the archive's own dir name is not ours
        if not _validate_skill_name(name, settings.skills_draft_dir / name):
            result.rejected.append((name[:64] or str(pkg), "invalid skill name"))
            continue

        if wanted is not None and name not in wanted:
            result.skipped.append((name, "not in requested names"))
            continue
        if (settings.skills_draft_dir / name).exists():
            result.skipped.append((name, "draft already exists — reject the old draft first"))
            continue
        if (settings.skills_dir / name).exists():
            result.skipped.append((name, "already published — use improve_skill, or rollback first"))
            continue

        try:
            result.installed.append(_install_one(pkg, name, source_uri, source_ref))
        except _Reject as e:
            result.rejected.append((name, str(e)))
        except Exception as e:
            logger.warning("Import of skill '%s' failed: %s", name, e)
            result.rejected.append((name, f"install failed: {e}"))

    if result.installed:
        _invalidate_skills_cache()
    return result


_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")
_ARCHIVE_CTYPES = {"application/zip", "application/gzip", "application/x-gzip", "application/x-tar",
                   "application/octet-stream"}
_MARKDOWN_CTYPES = {"text/markdown", "text/plain", "text/x-markdown"}
_GIT_HOST_RE = re.compile(r"^https?://(?:www\.)?(?:github|gitlab|bitbucket)\.(?:com|org)/[^/]+/[^/]+")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_entry_name(name: str) -> str:
    """Reject absolute / traversing archive entry names. Returns the normalized name."""
    # Explicit: a NUL would otherwise be rejected later by .resolve()'s lstat with a
    # misleading message, and only by accident.
    if "\x00" in name:
        raise ValueError(f"unsafe archive entry: {name!r}")
    norm = os.path.normpath(name)
    if os.path.isabs(norm) or norm.startswith(("/", "\\")) or norm == ".." or norm.startswith(".." + os.sep):
        raise ValueError(f"unsafe archive entry: {name}")
    return norm


def _safe_join(dest: Path, name: str) -> Path:
    out = (dest / _check_entry_name(name)).resolve()
    if not str(out).startswith(str(dest.resolve()) + os.sep):
        raise ValueError(f"unsafe archive entry: {name}")
    return out


def _check_entries(items: list[tuple[str, int, bool]]) -> None:
    """items = [(name, size, is_link_or_special)]. Raises on any hard-limit violation."""
    max_files = settings.skills_import_max_files
    if len(items) > max_files:
        raise ValueError(f"archive has too many files: {len(items)} > {max_files}")
    cap = settings.skills_import_max_package_bytes
    total = 0
    for name, size, is_special in items:
        _check_entry_name(name)
        if is_special:
            raise ValueError(f"archive contains a link/special entry: {name}")
        total += size
        if total > cap:
            raise ValueError(f"archive expands beyond {cap} bytes")


def _zip_is_link(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _unpack(archive: Path, dest: Path) -> None:
    """Explicit per-entry extraction. Never uses extractall.

    A corrupt or unreadable archive is a bad *source*, not a server fault, so the
    archive libraries' own exceptions are re-raised as ValueError (Task 9 maps
    ValueError -> HTTP 400). Our own ValueErrors pass through unwrapped.
    """
    try:
        dest.mkdir(parents=True, exist_ok=True)
        if archive.name.lower().endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                entries = [i for i in zf.infolist() if not i.is_dir()]
                _check_entries([(i.filename, i.file_size, _zip_is_link(i)) for i in entries])
                for info in entries:
                    out = _safe_join(dest, info.filename)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst, 65536)
                    os.chmod(out, 0o644)
        else:
            with tarfile.open(archive, "r:gz") as tf:
                members = [m for m in tf.getmembers() if not m.isdir()]
                _check_entries([(m.name, m.size, not m.isreg()) for m in members])
                for m in members:
                    out = _safe_join(dest, m.name)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    fobj = tf.extractfile(m)
                    if fobj is None:
                        raise ValueError(f"unreadable archive entry: {m.name}")
                    with open(out, "wb") as dst:
                        shutil.copyfileobj(fobj, dst, 65536)
                    os.chmod(out, 0o644)
    # zlib.error inherits straight from Exception (neither ValueError nor OSError), and a
    # corrupt deflate stream raises it from inside the decompressor, past the header checks.
    except (zipfile.BadZipFile, zipfile.LargeZipFile, tarfile.TarError,
            zlib.error, EOFError, OSError) as e:
        raise ValueError(f"cannot unpack archive {archive.name}: {type(e).__name__}: {e}") from e


def _download(url: str) -> tuple[bytes, str]:
    """Stream a URL into memory with a hard byte cap. Returns (bytes, content-type).

    A dead or typo'd URL is the likeliest real failure of this feature and is a bad
    *source*, so URLError/HTTPError/TimeoutError (all OSError subclasses) become
    ValueError -> HTTP 400. The cap's own ValueError is not an OSError, so it is
    never swallowed here.
    """
    cap = settings.skills_import_max_package_bytes
    req = urllib.request.Request(url, headers={"User-Agent": "aiops-skill-import"})
    chunks: list[bytes] = []
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=settings.skills_import_timeout_seconds) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                total += len(buf)
                if total > cap:
                    raise ValueError(f"download exceeds {cap} bytes")
                chunks.append(buf)
    except OSError as e:
        raise ValueError(f"download failed: {e}") from e
    return b"".join(chunks), ctype


def _is_git(uri: str) -> bool:
    if uri.startswith(("git+", "git@", "ssh://git@")):
        return True
    base = uri.split("#", 1)[0]
    if base.endswith(".git") or ".git@" in base:
        return True
    return bool(_GIT_HOST_RE.match(base)) and not base.lower().endswith(_ARCHIVE_SUFFIXES + (".md",))


_GIT_SCHEME_RE = re.compile(r"^(?:https|http|ssh|git|file)://", re.IGNORECASE)
_GIT_SCP_RE = re.compile(r"^[A-Za-z0-9._~+-]+@[A-Za-z0-9._-]+:")
# Variables that can re-enable a transport helper behind our back. GIT_ALLOW_PROTOCOL
# is a whitelist that OVERRIDES `-c protocol.<n>.allow=never`, so stripping it matters.
_GIT_ENV_STRIP = ("GIT_ALLOW_PROTOCOL", "GIT_PROTOCOL_FROM_USER")


def _validate_git_url(url: str) -> None:
    """Allowlist the git transport ourselves, before any argv exists.

    `<helper>::<cmd>` (`ext::`, `fd::`, any future helper) makes git RUN <cmd>, and
    neither `--` nor `-c protocol.ext.allow=never` stops it when GIT_ALLOW_PROTOCOL is
    set in the environment. So the helper and option-shape rejections below rely on no
    git behaviour whatsoever. Rejects run before accepts (fail closed).

    One residual: for an accepted `ssh://<host>/…` we do rely on git's own
    "strange hostname" check (git >= 2.14.1) to refuse an option-shaped host. The
    scp-style branch does NOT rely on git — git accepts an option-shaped scp host, so
    that case is rejected here explicitly.
    """
    if url.startswith("-"):
        raise ValueError(f"unsupported git transport (option-shaped url): {url}")
    if "::" in url.split("/", 1)[0]:
        raise ValueError(f"unsupported git transport (transport helper): {url}")
    if _GIT_SCP_RE.match(url):
        if url.split("@", 1)[1].startswith("-"):
            raise ValueError(f"unsupported git transport (option-shaped host): {url}")
        return
    if _GIT_SCHEME_RE.match(url):
        return
    try:
        if Path(url).expanduser().exists():
            return
    except OSError:
        # e.g. ENAMETOOLONG — an unusable path is simply not an accepted transport.
        pass
    raise ValueError(f"unsupported git transport: {url}")


def _git_env() -> dict[str, str]:
    """Subprocess env for git: real environment minus the transport-helper escapes.

    NOT a sandbox — cloning legitimately needs PATH, HOME and the SSH agent vars.
    GIT_TERMINAL_PROMPT=0 makes a credential-needing URL fail fast instead of hanging.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_STRIP}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _fetch_git(uri: str, workdir: Path) -> tuple[Path, str]:
    url = uri[4:] if uri.startswith("git+") else uri
    subdir = ""
    if "#" in url:
        url, subdir = url.split("#", 1)
    ref = ""
    last = url.rsplit("/", 1)[-1]
    if "@" in last:
        url, ref = url.rsplit("@", 1)

    _validate_git_url(url)
    env = _git_env()

    dest = workdir / "repo"
    cmd = ["git", "-c", "protocol.ext.allow=never", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += ["--", url, str(dest)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, shell=False, env=env,
            timeout=settings.skills_import_timeout_seconds,
        )
        if proc.returncode != 0:
            raise ValueError(f"git clone failed: {proc.stderr.strip()[:300]}")

        sha = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, shell=False, env=env, timeout=30,
        ).stdout.strip()
    except subprocess.SubprocessError as e:
        raise ValueError(f"git clone failed: {type(e).__name__}: {e}") from e
    except OSError as e:
        raise ValueError(f"git clone failed: {e}") from e
    shutil.rmtree(dest / ".git", ignore_errors=True)

    root = dest
    if subdir:
        root = (dest / _check_entry_name(subdir)).resolve()
        if not str(root).startswith(str(dest.resolve()) + os.sep) or not root.is_dir():
            raise ValueError(f"subdir not found in repo: {subdir}")
    return root, sha or "unknown"


def _fetch_http(uri: str, workdir: Path) -> tuple[Path, str]:
    data, ctype = _download(uri)
    path_part = urlparse(uri).path.lower()

    if path_part.endswith(_ARCHIVE_SUFFIXES) or ctype in _ARCHIVE_CTYPES:
        is_zip = path_part.endswith(".zip") or ctype == "application/zip" or data[:2] == b"PK"
        tmp = workdir / ("download.zip" if is_zip else "download.tar.gz")
        tmp.write_bytes(data)
        dest = workdir / "unpacked"
        _unpack(tmp, dest)
        return dest, _sha256_bytes(data)

    if path_part.endswith(".md") or ctype in _MARKDOWN_CTYPES:
        text = data.decode("utf-8", errors="replace")
        fm, _ = parse_frontmatter(text)
        raw = (fm.get("name") if isinstance(fm, dict) else None) or Path(urlparse(uri).path).stem
        # Sanitize only the DIRECTORY name; the frontmatter name still faces full validation later.
        dirname = re.sub(r"[^a-z0-9-]", "-", str(raw).lower())[:64].strip("-") or "imported-skill"
        root = workdir / "single"
        pkg = root / dirname
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "SKILL.md").write_text(text, encoding="utf-8")
        return root, _sha256_bytes(data)

    raise ValueError(f"unsupported skill source: {uri} (content-type={ctype or 'unknown'})")


def fetch(uri: str, workdir: Path) -> tuple[Path, str]:
    """Resolve a skill source into a local root directory + a provenance ref."""
    if _is_git(uri):
        return _fetch_git(uri, workdir)
    if uri.startswith(("http://", "https://")):
        return _fetch_http(uri, workdir)

    p = Path(uri).expanduser()
    if p.is_dir():
        return p, "local-dir"
    if p.is_file() and p.name.lower().endswith(_ARCHIVE_SUFFIXES):
        dest = workdir / "unpacked"
        _unpack(p, dest)
        return dest, _sha256_file(p)
    raise ValueError(f"unsupported skill source: {uri}")


def import_skills(uri: str, names: list[str] | None = None) -> ImportResult:
    """Import skills from a URL / git repo / zip / local path as DRAFTS.

    Human action only — no agent tool calls this. Nothing in the package is
    executed. Raises on source-level failure (nothing written); per-package
    problems are reported in ImportResult.skipped / .rejected.
    """
    if not settings.skills_import_enabled:
        raise RuntimeError("skill import is disabled (skills_import_enabled=false)")

    workdir = Path(tempfile.mkdtemp(prefix="aiops-skill-import-"))
    try:
        root, source_ref = fetch(uri, workdir)
        pkgs = discover_packages(root)
        if not pkgs:
            raise ValueError(f"no SKILL.md found in source: {uri}")
        result = install_packages(pkgs, uri, source_ref, names)
        logger.info(
            "Skill import from %s (ref=%s): %d installed, %d skipped, %d rejected",
            uri, source_ref[:12], len(result.installed), len(result.skipped), len(result.rejected),
        )
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
