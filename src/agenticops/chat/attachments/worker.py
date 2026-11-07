"""Run extraction in a child process (2026-11-07).

AgenticOps runs as ONE process; a native parser that crashes, hangs or balloons on a hostile file (PyMuPDF, libheif,
lxml) must not take the chat, the scheduler and every agent down with it. The parent gives the child a deadline and
an environment without any AWS_* variable (the child needs no credentials); on Linux the child limits its own
address space to 2 GiB before it parses anything. This is crash / hang / memory containment, not a sandbox: the
child runs as the service user, with its file access and the rest of its environment.

    python -m agenticops.chat.attachments.worker <src> <ext> <out_dir> <limits-json>

The child writes `out_dir/meta.json` (exit 0) or `out_dir/error.json` {"reason"} (exit 3); its stderr goes to
`out_dir/worker.err`. Three environment switches exist for the tests only (a subprocess cannot be monkeypatched):
AIOPS_ATTACHMENT_WORKER_TEST_SLEEP=<s>, AIOPS_ATTACHMENT_WORKER_TEST_CRASH=1, AIOPS_ATTACHMENT_WORKER_TEST_ENV=1.
"""
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from agenticops.chat.attachments.extract import ExtractError, ExtractLimits, process

ADDRESS_SPACE_LIMIT = 2 * 1024**3
_ERR_TAIL = 2000


@dataclass
class WorkerResult:
    ok: bool
    meta: dict = field(default_factory=dict)
    reason: Optional[str] = None


def _child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    return env


def _limit_memory() -> None:  # pragma: no cover — runs in the child, Linux only
    """Set in the child's own main(), never through preexec_fn (unsafe in the threaded service, and it would turn
    off the fast spawn path): the parsers are imported lazily, after this."""
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_LIMIT, ADDRESS_SPACE_LIMIT))
    except (ValueError, OSError) as e:   # keep working on the deadline alone rather than refuse every upload
        print(f"address-space limit not set: {e}", file=sys.stderr)


def run(src: Path, ext: str, out_dir: Path, lim: ExtractLimits, timeout: float = 120.0) -> WorkerResult:
    """Extract `src` into `out_dir` in a child process. Never raises for a bad file: the result says why."""
    out_dir = Path(out_dir)
    cmd = [sys.executable, "-m", "agenticops.chat.attachments.worker", str(src), ext, str(out_dir),
           json.dumps(asdict(lim))]
    with open(out_dir / "worker.err", "wb") as err:
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                  env=_child_env(), timeout=timeout)
        except subprocess.TimeoutExpired:   # subprocess.run kills the child before raising
            return WorkerResult(False, reason="timeout")
    if proc.returncode == 0 and (out_dir / "meta.json").is_file():
        return WorkerResult(True, meta=json.loads((out_dir / "meta.json").read_text()))
    if (out_dir / "error.json").is_file():
        return WorkerResult(False, reason=json.loads((out_dir / "error.json").read_text()).get("reason") or "corrupt")
    return WorkerResult(False, reason="worker_crashed")


def stderr_tail(out_dir: Path) -> str:
    """The end of the child's stderr, for the log (never shown to the user)."""
    try:
        data = (Path(out_dir) / "worker.err").read_bytes()
    except OSError:
        return ""
    return data[-_ERR_TAIL:].decode("utf-8", "replace")


def main(argv: list[str]) -> int:
    if os.environ.get("AIOPS_ATTACHMENT_WORKER_TEST_SLEEP"):        # test only: a hung parser
        import time
        time.sleep(float(os.environ["AIOPS_ATTACHMENT_WORKER_TEST_SLEEP"]))
    if os.environ.get("AIOPS_ATTACHMENT_WORKER_TEST_CRASH"):        # test only: a native crash
        os.abort()
    if sys.platform.startswith("linux"):
        _limit_memory()
    src, ext, out_dir, lim_json = argv
    out = Path(out_dir)
    if os.environ.get("AIOPS_ATTACHMENT_WORKER_TEST_ENV"):          # test only: what the child sees
        (out / "env.json").write_text(json.dumps(sorted(os.environ)))
    try:
        meta = process(Path(src), ext, out, ExtractLimits(**json.loads(lim_json)))
    except ExtractError as e:
        print(f"extract refused: {e}", file=sys.stderr)
        (out / "error.json").write_text(json.dumps({"reason": e.reason}))
        return 3
    except OSError as e:   # the source vanished or cannot be read
        print(f"extract failed: {e}", file=sys.stderr)
        (out / "error.json").write_text(json.dumps({"reason": "unreadable"}))
        return 3
    (out / "meta.json").write_text(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
