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

* **`skills_sandbox_max_output_chars` bounds what we STORE, and the two deadlines
  bound how long we read.** Output is captured by `_Capture`, a `select` loop over
  both pipes (and the stdin feed) that keeps *reading* past the cap — so the child
  can never deadlock us on a pipe it has filled — while *storing* at most `cap`
  bytes per stream. Memory is therefore O(cap) rather than O(what the child wrote),
  and the wall clock is bounded by `timeout + _KILL_GRACE_SECONDS` for every payload
  shape. This replaced `communicate()`, which delivered neither bound: a plain
  `while True: sys.stdout.write('A' * 65536)` — no fork, no evasion primitive, on no
  bundle-scan rule, so the promoting human sees nothing — measured **7.4s against a
  1s timeout and 2.99 GB of resident memory in the service process**, because
  `TimeoutExpired`'s constructor joins every chunk buffered so far. That is a denial
  of service on the AgenticOps process, not on the sandboxed child. Do not
  "simplify" this back into `communicate()`.
"""

from __future__ import annotations

import logging
import os
import select
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

_READ_CHUNK = 65536


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


class _Capture:
    """Deadline-driven, memory-bounded capture of a child's stdout/stderr + stdin feed.

    Replaces `communicate()`, which is wrong here in two *measured* ways:

    * **Memory.** `communicate()` buffers everything the child writes before any cap is
      applied. `while True: sys.stdout.write('A' * 65536)` — no fork, no evasion, matched
      by no bundle-scan rule — cost **2.99 GB** of resident memory in the service process
      at a 1s timeout. Here we stop STORING at `cap` bytes per stream but keep READING, so
      memory is O(cap) while the child still cannot deadlock on a pipe it has filled.
    * **Time.** `communicate(timeout=…)` raises `TimeoutExpired`, whose constructor joins
      every chunk buffered so far (`subprocess.py:1255`) and allocates a second copy — work
      proportional to what the child wrote. That join, not the reading, is why the same 1s
      timeout took **7.4s** to return. Nothing on `pump`'s deadline path is proportional to
      what arrived: the check is a clock comparison and the join is over ≤ `cap` bytes.

    Both pipes AND stdin are driven by one `select` loop over non-blocking fds. Reading one
    pipe to EOF while the child fills the other is the classic deadlock `communicate()`
    exists to avoid, and so is writing stdin to a child that never reads it.

    This is an object rather than a function because the state must survive ACROSS the two
    deadlines `run_script` uses — the timeout, then the post-kill grace. The second `pump`
    continues the first one's buffers instead of restarting them, which is what
    `communicate()`-after-`TimeoutExpired` did.
    """

    def __init__(self, proc: subprocess.Popen, stdin_bytes: bytes, cap: int) -> None:
        self._proc = proc
        self._cap = max(0, cap)
        self._out: list[bytes] = []
        self._err: list[bytes] = []
        # fd -> {"sink": list, "stored": bytes kept, "produced": bytes the child wrote}
        self._tracked: dict[int, dict] = {}
        self._active: set[int] = set()
        for pipe, sink in ((proc.stdout, self._out), (proc.stderr, self._err)):
            if pipe is None:
                continue
            fd = pipe.fileno()
            os.set_blocking(fd, False)
            self._tracked[fd] = {"sink": sink, "stored": 0, "produced": 0}
            self._active.add(fd)

        self._stdin = proc.stdin
        self._view = memoryview(stdin_bytes)
        self._sent = 0
        if self._stdin is not None:
            os.set_blocking(self._stdin.fileno(), False)
            if not stdin_bytes:
                self._close_stdin()

    @property
    def over_cap(self) -> bool:
        """True when the child PRODUCED more than the cap — whether or not we stored it."""
        return any(t["produced"] > self._cap for t in self._tracked.values())

    def text(self) -> tuple[str, str]:
        """Decode the stored bytes once, replacing anything that is not UTF-8.

        A child is free to emit bytes that are not UTF-8: `sys.stdout.buffer.write(b'\\xff')`
        matches no bundle-scan rule, and any honest script that re-emits raw log bytes or a
        latin-1 line does it by accident. `text=True` on `Popen` decoded strictly, so such a
        SUCCESSFUL run raised `UnicodeDecodeError` (a `ValueError`, not a `RuntimeError`) out
        of `run_script` — a completed run reported as a crash, which is the worst way to break
        the refusals-are-RuntimeError contract.
        """
        return (
            b"".join(self._out).decode("utf-8", errors="replace"),
            b"".join(self._err).decode("utf-8", errors="replace"),
        )

    def pump(self, deadline: float) -> bool:
        """Drive both pipes and the stdin feed until EOF on both, or until `deadline`.

        Returns True if the deadline was reached with a pipe still open (i.e. someone is
        still holding a write end), False if both pipes reached EOF in time.
        """
        while self._active or self._stdin is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            wlist = [self._stdin.fileno()] if self._stdin is not None else []
            try:
                readable, writable, _ = select.select(
                    list(self._active), wlist, [], remaining
                )
            except (OSError, ValueError):
                # A pipe was closed underneath us; there is nothing left to read.
                break
            for fd in readable:
                self._read(fd)
            if writable:
                self._write()
        return False

    def _read(self, fd: int) -> None:
        try:
            data = os.read(fd, _READ_CHUNK)
        except BlockingIOError:
            return
        except OSError:
            self._active.discard(fd)
            return
        if not data:
            self._active.discard(fd)          # EOF
            return
        rec = self._tracked[fd]
        rec["produced"] += len(data)
        room = self._cap - rec["stored"]
        if room > 0:
            kept = data[:room]
            rec["sink"].append(kept)
            rec["stored"] += len(kept)
        # Past the cap the bytes are read (above) and dropped. Reading is what keeps the
        # child from blocking on a full pipe; dropping is what keeps memory at O(cap).

    def _write(self) -> None:
        if self._stdin is None:
            return
        try:
            self._sent += os.write(self._stdin.fileno(), self._view[self._sent:])
        except BlockingIOError:
            return
        except OSError:
            # EPIPE and friends: the child closed stdin or exited without reading it.
            self._close_stdin()
            return
        if self._sent >= len(self._view):
            self._close_stdin()

    def _close_stdin(self) -> None:
        pipe, self._stdin = self._stdin, None
        _close_quietly(pipe)

    def close(self) -> None:
        """Release our ends of all three pipes. Idempotent."""
        self._close_stdin()
        self._active.clear()
        for pipe in (self._proc.stdout, self._proc.stderr):
            _close_quietly(pipe)


def _close_quietly(pipe) -> None:
    try:
        if pipe is not None:
            pipe.close()
    except OSError:
        pass


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
    # Every syscall on a caller-supplied path is inside this ONE block: resolve() raises
    # ValueError on an embedded NUL, and is_file() raises OSError (ENAMETOOLONG) on a path
    # component the OS will not accept. Both are refusals, and the contract is that every
    # refusal is a RuntimeError. The escape check stays between them — it must run before
    # we stat, and its RuntimeError passes straight through this except clause.
    try:
        root = skill_dir.resolve()
        target = (skill_dir / script).resolve()
        if not str(target).startswith(str(root) + os.sep):
            raise RuntimeError(f"script path escapes the skill package: {script}")
        exists = target.is_file()
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"script path is not a usable path: {script!r} ({exc})") from exc
    if not exists:
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
    path, bad suffix, no isolator, an unreadable packaged script, stdin_text that
    is not UTF-8-encodable, and an interpreter/isolator that will not start.
    Task 8's @tool catches RuntimeError to render a refusal, so a refusal must
    never surface as some other exception type. A script that runs and fails
    returns a SandboxResult with its exit code — a refusal is never reported as a
    failed run, and conversely a run that SUCCEEDS never raises: output that is
    not valid UTF-8 is decoded with replacement, not rejected.
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

    # Encode here, not inside the capture loop: a lone surrogate (which model-generated text
    # can carry) is a refusal of the CALL, and must not surface as a bare UnicodeEncodeError.
    try:
        stdin_bytes = (stdin_text or "").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RuntimeError(f"stdin_text is not encodable as UTF-8: {exc}") from exc

    workdir = Path(tempfile.mkdtemp(prefix="aiops-skill-sandbox-"))
    timeout = settings.skills_sandbox_timeout_seconds
    try:
        # copy2 copies exactly ONE file: packaged siblings stay out of the cwd.
        local = workdir / target.name
        try:
            shutil.copy2(target, local)
            os.chmod(local, 0o600)                   # no exec bit — we name the interpreter
        except (OSError, shutil.Error) as exc:
            # An unreadable packaged script (a zip/URL import can carry mode 000) is a
            # refusal, not a crash: nothing ran.
            raise RuntimeError(
                f"could not stage the skill script in the sandbox: {script} ({exc})"
            ) from exc

        env = _build_env(workdir)
        cmd = _wrap([interpreter, str(local), *(args or [])], isolation)

        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workdir), env=env, shell=False,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,              # own process group, so we can kill it whole
            )
        except (OSError, ValueError) as exc:
            # Nothing ran: the interpreter or the isolator is not on the child's minimal
            # PATH (Popen resolves via os.get_exec_path(env), not the ambient PATH).
            # Fail closed as a refusal, not as an unhandled exception in Task 8's @tool.
            raise RuntimeError(f"could not start the sandboxed script: {cmd[0]!r} ({exc})") from exc

        cap = settings.skills_sandbox_max_output_chars
        capture = _Capture(proc, stdin_bytes, cap)
        try:
            timed_out = capture.pump(started + timeout)
            if not timed_out:
                # Both pipes hit EOF in time, so the child is normally already gone. wait()
                # is bounded by the SAME deadline, and its TimeoutExpired carries no output —
                # O(1), unlike communicate()'s, whose join is what F1 measured.
                try:
                    proc.wait(timeout=max(0.0, (started + timeout) - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True

            if not timed_out:
                out, err = capture.text()
                exit_code = proc.returncode
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
                exit_code = -1
                # BOUNDED second read. Waiting for EOF on both pipes is unbounded: a
                # descendant that left our process group (fork+setsid) still holds them, so
                # the script, not the timeout, would decide when we return.
                grace_deadline = time.monotonic() + _KILL_GRACE_SECONDS
                if capture.pump(grace_deadline):
                    capture.close()
                    proc.kill()
                    proc.poll()      # reap the direct child; escaped descendants survive
                    # Never claim a clean kill here: the read was cut short, so something is
                    # still holding a write end open. We DO hold a capped prefix at this point
                    # (pump bounds it) — it is dropped because it is a fragment of a run that
                    # may still be producing, not because it is unretrievable.
                    out, err = "", (
                        f"[sandbox] {timeout}s timeout expired and SIGKILL was sent to the "
                        f"process group, but the output was ABANDONED after a further "
                        f"{_KILL_GRACE_SECONDS}s: a descendant escaped the process group and "
                        f"still holds the pipes, so it MAY STILL BE RUNNING"
                    )
                else:
                    try:
                        proc.wait(timeout=max(0.0, grace_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
                    out, err = capture.text()
                    err = err + f"\n[sandbox] killed after {timeout}s timeout"
            over_cap = capture.over_cap
        finally:
            capture.close()
        duration_ms = int((time.monotonic() - started) * 1000)

        # The cap is enforced while READING now, so what we kept can never exceed it —
        # comparing len(out) to cap (which is how this was computed when communicate()
        # buffered everything) would report truncated=False for a child that wrote GBs.
        # The produced-byte counters are the only honest source.
        truncated = over_cap
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
