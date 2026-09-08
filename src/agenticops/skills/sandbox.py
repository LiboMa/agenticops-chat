"""Restricted sandbox for skill-owned scripts (*.py / *.sh).

A new execution channel, orthogonal to run_on_host / run_kubectl. In order of
trust, every run gets:

1. published skills only (drafts are refused — approval comes first);
2. a path-traversal guard on the script, plus an interpreter allowlist keyed on
   suffix (never a shebang, never the exec bit, never shell=True);
3. an env built from an EMPTY dict — only PATH/HOME/LANG — so no AWS_* or
   AIOPS_* variable can structurally appear inside the child;
4. network isolation via `unshare -n` (Linux) or `sandbox-exec` (macOS); with
   skills_sandbox_require_isolation set (the default) a missing isolator means
   REFUSE, never a silent unisolated run. We never claim isolation we don't have;
5. a one-shot temp cwd (deleted afterwards, so scripts cannot write back into
   the skill package), a timeout that kills the process group, and output
   truncation.

The sandbox has no credentials and no network on purpose: skill scripts are for
local computation (parsing logs/JSON, statistics, report shaping). Anything that
needs a cloud API still goes through run_aws_cli / run_on_host / run_kubectl and
their existing three-tier gates.

Three properties are deliberate and must not be "improved" away:

* **The interpreter is keyed on the file suffix — never on the shebang, never on
  the exec bit.** A Python payload in a `.sh` file is handed to /bin/bash and a
  shell payload in a `.py` file is handed to the Python interpreter; both simply
  fail with a syntax error. That is exactly what makes a shebang/suffix mismatch
  non-exploitable: honouring a shebang would let a `.py` file (which the bundle
  scan reads with Python rules) execute as an arbitrary interpreter of the
  author's choosing. The copied script is chmod 0o600 — not executable — so it
  cannot be launched by anything but the interpreter we name.

* **Only the target script is copied into the one-shot cwd.** Sibling files that
  shipped in the same skill package are NOT present at run time, so a script
  cannot `source ./helper.sh`, `compile(open('payload.txt').read())` or read a
  packaged data file. This is load-bearing rather than cosmetic: the bundle scan
  (skills/security.scan_skill_bundle) only scans `*.py`/`*.sh`, so a `.txt`,
  `.json` or `.yaml` payload in the package is unscanned — leaving it out of the
  cwd is what keeps it un-executable.

* **The sandbox denies network and supplies no credentials, but it does NOT
  confine filesystem writes.** A sandboxed script runs as the service user with
  that user's ordinary read/write access to the whole filesystem; the one-shot
  cwd only means its *relative* writes are discarded. Destructive-filesystem
  behaviour is therefore blocked by the bundle scan at promote time and by
  nothing at run time — those scan rules are a real boundary, not
  defence-in-depth behind a filesystem jail.

* **The timeout bounds OUR wait, not the life of every descendant.** A script
  that calls `os.fork()` + `os.setsid()` puts its child in a new session, so the
  SIGKILL we send to our own process group never reaches it, and there is no
  cgroup and no PID namespace here to catch it — a non-container sandbox cannot
  reap it. What the bounded grace after the kill guarantees is that `run_script`
  RETURNS; an escaped grandchild keeps running afterwards, and when that happens
  the returned stderr says so instead of claiming a clean kill. Do not read the
  timeout as "every descendant is dead".

* **`skills_sandbox_max_output_chars` bounds what we RETURN, not what we READ.**
  `communicate()` buffers the child's entire output before the cap is applied, so
  a runaway script is a memory-exhaustion risk in the service process rather than
  a truncated result. The mitigation is the timeout above — the window is
  `timeout × output rate`, and that is only bounded *because* the timeout now
  bounds the run. The real fix (a deadlock-safe incremental read of both pipes)
  is a recorded follow-up.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from agenticops.config import settings
from agenticops.skills.loader import _validate_skill_name

logger = logging.getLogger(__name__)

# macOS seatbelt profile: everything allowed except the network.
_SANDBOX_PROFILE = "(version 1)(allow default)(deny network*)"

_ISOLATION_CACHE: str | None = None

# Grace given to the post-kill output read. A descendant that left our process group
# still holds the inherited pipes, so an unbounded read would let the child decide how
# long run_script blocks; past this we abandon the output instead of waiting.
_KILL_GRACE_SECONDS = 5


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    duration_ms: int
    isolation: str          # 'unshare' | 'sandbox-exec' | 'none'


def detect_isolation() -> str:
    """Probe for a usable network isolator. Cached — the answer cannot change."""
    global _ISOLATION_CACHE
    if _ISOLATION_CACHE is not None:
        return _ISOLATION_CACHE

    result = "none"
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        try:
            probe = subprocess.run(
                ["unshare", "-n", "--", "true"],
                capture_output=True, shell=False, timeout=10,
            )
            if probe.returncode == 0:
                result = "unshare"
        except (OSError, subprocess.SubprocessError):
            result = "none"
    elif sys.platform == "darwin" and shutil.which("sandbox-exec"):
        result = "sandbox-exec"

    if result == "none":
        logger.warning(
            "No skill-script network isolator available on this host "
            "(need `unshare -n` on Linux or `sandbox-exec` on macOS)"
        )
    _ISOLATION_CACHE = result
    return result


def _wrap(cmd: list[str], isolation: str) -> list[str]:
    if isolation == "unshare":
        return ["unshare", "-n", "--", *cmd]
    if isolation == "sandbox-exec":
        return ["sandbox-exec", "-p", _SANDBOX_PROFILE, *cmd]
    return cmd


def _build_env(workdir: Path) -> dict[str, str]:
    """The child's whole environment, built from an EMPTY dict.

    os.environ is never consulted, so no credential the service process holds
    (AWS_*, AIOPS_*, assumed-role session values) can reach a skill script.
    PATH stays minimal on purpose: Popen resolves the executable through
    os.get_exec_path(env), and /usr/bin:/bin is enough for /bin/bash, unshare
    and sandbox-exec. Inheriting the ambient PATH would weaken this.
    """
    return {"PATH": "/usr/bin:/bin", "HOME": str(workdir), "LANG": "C.UTF-8"}


def _resolve_script(skill_name: str, script: str) -> Path:
    """Published-skill + path-traversal + suffix-allowlist resolution."""
    name = (skill_name or "").strip()
    skill_dir = settings.skills_dir / name
    if not _validate_skill_name(name, skill_dir):
        raise RuntimeError(f"invalid skill name: {skill_name!r}")

    if not (skill_dir / "SKILL.md").is_file():
        if (settings.skills_draft_dir / name / "SKILL.md").is_file():
            raise RuntimeError(
                f"skill '{name}' is still a draft — promote it before running its scripts"
            )
        raise RuntimeError(f"published skill not found: {name}")

    # resolve() both sides: a symlink inside the package that points outside it
    # resolves to its target and is then caught by the escape check below.
    # resolve() raises ValueError on an embedded NUL and OSError on a hostile path;
    # both are refusals, and the contract is that every refusal is a RuntimeError.
    try:
        root = skill_dir.resolve()
        target = (skill_dir / script).resolve()
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"script path is not a usable path: {script!r} ({exc})") from exc
    if not str(target).startswith(str(root) + os.sep):
        raise RuntimeError(f"script path escapes the skill package: {script}")
    if not target.is_file():
        raise RuntimeError(f"script does not exist: {script}")

    interpreters = settings.skills_sandbox_interpreters
    if target.suffix.lower() not in interpreters:
        raise RuntimeError(
            f"script type not allowed: {target.suffix} (allowed: {sorted(interpreters)})"
        )
    return target


def run_script(
    skill_name: str,
    script: str,
    args: list[str] | None = None,
    stdin_text: str | None = None,
) -> SandboxResult:
    """Run a PUBLISHED skill's script in the restricted sandbox.

    Raises RuntimeError for EVERY refusal — disabled, draft, bad path, unusable
    path, bad suffix, no isolator, and an interpreter/isolator that will not
    start. Task 8's @tool catches RuntimeError to render a refusal, so a refusal
    must never surface as some other exception type. A script that runs and
    fails returns a SandboxResult with its exit code — a refusal is never
    reported as a failed run.
    """
    if not settings.skills_sandbox_enabled:
        raise RuntimeError("skill script sandbox is disabled (skills_sandbox_enabled=false)")

    target = _resolve_script(skill_name, script)

    isolation = detect_isolation()
    if isolation == "none" and settings.skills_sandbox_require_isolation:
        raise RuntimeError(
            "no network isolator available (unshare -n / sandbox-exec) — refusing to run; "
            "set skills_sandbox_require_isolation=false to accept an explicitly UNISOLATED run"
        )

    interpreter = settings.skills_sandbox_interpreters[target.suffix.lower()]
    if interpreter == "python":
        interpreter = sys.executable

    workdir = Path(tempfile.mkdtemp(prefix="aiops-skill-sandbox-"))
    timeout = settings.skills_sandbox_timeout_seconds
    try:
        # copy2 copies exactly ONE file: packaged siblings stay out of the cwd.
        local = workdir / target.name
        shutil.copy2(target, local)
        os.chmod(local, 0o600)                       # no exec bit — we name the interpreter

        env = _build_env(workdir)
        cmd = _wrap([interpreter, str(local), *(args or [])], isolation)

        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workdir), env=env, shell=False, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,              # own process group, so we can kill it whole
            )
        except (OSError, ValueError) as exc:
            # Nothing ran: the interpreter or the isolator is not on the child's minimal
            # PATH (Popen resolves via os.get_exec_path(env), not the ambient PATH).
            # Fail closed as a refusal, not as an unhandled exception in Task 8's @tool.
            raise RuntimeError(f"could not start the sandboxed script: {cmd[0]!r} ({exc})") from exc
        try:
            out, err = proc.communicate(input=stdin_text or "", timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            try:
                # BOUNDED read. An unbounded communicate() waits for EOF on both pipes,
                # and a descendant that left our process group (fork+setsid) still holds
                # them — so the script, not the timeout, would decide when we return.
                out, err = proc.communicate(timeout=_KILL_GRACE_SECONDS)
                err = (err or "") + f"\n[sandbox] killed after {timeout}s timeout"
            except subprocess.TimeoutExpired:
                proc.kill()
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        if pipe is not None:
                            pipe.close()
                    except OSError:
                        pass
                proc.poll()          # reap the direct child; escaped descendants survive
                # Never claim a clean kill here: the read was cut short, so the output is
                # incomplete and something is still holding the pipes open.
                out, err = "", (
                    f"[sandbox] {timeout}s timeout expired and SIGKILL was sent to the "
                    f"process group, but the output was ABANDONED after a further "
                    f"{_KILL_GRACE_SECONDS}s: a descendant escaped the process group and "
                    f"still holds the pipes, so it MAY STILL BE RUNNING"
                )
            exit_code = -1
        duration_ms = int((time.monotonic() - started) * 1000)

        cap = settings.skills_sandbox_max_output_chars
        out, err = out or "", err or ""
        truncated = len(out) > cap or len(err) > cap
        logger.info(
            "Sandbox ran %s/%s: exit=%s isolation=%s duration_ms=%s%s",
            skill_name, script, exit_code, isolation, duration_ms,
            " (UNISOLATED)" if isolation == "none" else "",
        )
        return SandboxResult(
            exit_code=exit_code,
            stdout=out[:cap],
            stderr=err[:cap],
            truncated=truncated,
            duration_ms=duration_ms,
            isolation=isolation,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
