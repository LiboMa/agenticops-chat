"""Restricted skill-script sandbox. Hermetic: no network, no credentials, no real AWS.

Tests that actually execute a script force isolation='none' + require_isolation=False so
they run identically on Linux and macOS; the isolation contract itself is tested separately.
"""

from pathlib import Path

import pytest


SKILL_MD = "---\nname: {name}\ndescription: sandbox probe\n---\n\nbody\n"

# Keys a platform runtime injects into a child's OWN environ during process init,
# i.e. NOT inherited from the env dict we hand to Popen. macOS CoreFoundation writes
# __CF_USER_TEXT_ENCODING when CF initialises inside the child; `/usr/bin/printenv`
# (no CF init) run through the same code path sees exactly PATH/HOME/LANG, which is
# what test_env_dict_is_exactly_three_keys pins by exact equality. Subtracting this
# fixed, value-less-for-an-attacker key keeps the assertion below an exact-subset
# check — it is never relaxed into a prefix/startswith check.
_PLATFORM_INJECTED = {"__CF_USER_TEXT_ENCODING"}

# fork()+setsid() moves the child into a NEW session, so the SIGKILL the sandbox sends to
# its own process group never reaches it — while it still holds the inherited stdout/stderr
# write ends open. An unbounded post-kill read then blocks for as long as this script cares
# to live (30s here; 86400 for an attacker). scan_skill_bundle passes this payload clean:
# os.fork / os.setsid / time.sleep are on no rule, so the promoting human sees nothing.
ESCAPING_SCRIPT = (
    "import os, sys, time\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    os.setsid()\n"
    "    time.sleep(30)\n"
    "    os._exit(0)\n"
    "open(sys.argv[1], 'w').write(str(pid))\n"
    "time.sleep(30)\n"
)

# No fork, no setsid, nothing scan_skill_bundle has a rule for — an honest
# `while True: print(...)` bug does this by accident. Under communicate() this was bounded
# by neither time nor memory: 7.4s against a 1s timeout and 2.99 GB of resident memory in
# the SERVICE process (an OOM here takes down the platform, not the skill), because
# TimeoutExpired's constructor joins every buffered chunk.
FLOODING_SCRIPT = "import sys\nwhile True:\n    sys.stdout.write('A' * 65536)\n"


@pytest.fixture
def spare_fds():
    """Hold ~1200 spare fds open so a child's pipe fds land above FD_SETSIZE (1024).

    Closes every fd it opened, always: a leaked fd table would corrupt every later test in
    this file, and this file is the only suite that can be run scoped.
    """
    import os
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    restore = None
    if soft < 2048:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, hard), hard))
            restore = (soft, hard)
        except (ValueError, OSError):
            pytest.skip(f"cannot raise RLIMIT_NOFILE above {soft} to reach FD_SETSIZE")

    held: list[int] = []
    try:
        while len(held) < 1200:
            held.append(os.open(os.devnull, os.O_RDONLY))
        yield max(held)
    finally:
        for fd in held:
            try:
                os.close(fd)
            except OSError:
                pass
        if restore is not None:
            resource.setrlimit(resource.RLIMIT_NOFILE, restore)


def _peak_rss_mb() -> float:
    """High-water RSS of the test process in MB (darwin reports bytes, Linux KB)."""
    import resource
    import sys

    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch):
    """Published + draft dirs, sandbox enabled, isolation forced off (portable)."""
    from agenticops.skills import sandbox
    from agenticops.skills.loader import _invalidate_skills_cache

    sdir = tmp_path / "skills"
    ddir = sdir / "draft"
    ddir.mkdir(parents=True)
    monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_sandbox_enabled", True, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_sandbox_require_isolation", False, raising=False)
    monkeypatch.setattr(sandbox, "detect_isolation", lambda: "none")
    _invalidate_skills_cache()
    yield sdir, ddir
    _invalidate_skills_cache()


def _publish(sdir: Path, name: str, files: dict[str, str]) -> Path:
    d = sdir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


class TestSandboxGates:
    def test_disabled_refuses(self, sandbox_env, monkeypatch):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_enabled", False, raising=False)

        with pytest.raises(RuntimeError, match="disabled"):
            run_script("alpha-skill", "hi.sh")

    def test_draft_skill_refuses(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        _sdir, ddir = sandbox_env
        _publish(ddir, "draft-skill", {"hi.sh": "echo hi\n"})

        # Must match text unique to the DRAFT branch: a bare "draft" also matches the
        # skill name in the generic "published skill not found: draft-skill" fallback,
        # so deleting the draft branch would leave this test green.
        with pytest.raises(RuntimeError, match="still a draft"):
            run_script("draft-skill", "hi.sh")

    def test_unknown_skill_refuses(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        with pytest.raises(RuntimeError, match="not found"):
            run_script("ghost-skill", "hi.sh")

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "../draft/x.sh"])
    def test_script_path_traversal_refused(self, sandbox_env, bad):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})

        with pytest.raises(RuntimeError, match="escapes|does not exist"):
            run_script("alpha-skill", bad)

    @pytest.mark.parametrize("bad", [
        "../../outside/evil.sh",        # real file, relative traversal out of skills_dir
        "../draft/draft-skill/hi.sh",   # real DRAFT script — must not defeat the draft gate
        "../alpha-skill-evil/x.sh",     # real sibling whose dir name PREFIXES the package
    ])
    def test_existing_file_outside_package_refused_as_escape(self, sandbox_env, bad):
        """Every target here EXISTS with an allowed suffix, so the refusal can only come
        from the escape check — never from the 'does not exist' branch. Weakening the
        check to 'absolute paths only', or to an unanchored substring test (which the
        prefix-sibling case defeats), lets one of these RUN."""
        from agenticops.skills.sandbox import run_script

        sdir, ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        outside = sdir.parent / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "evil.sh").write_text("echo OUTSIDE-RAN\n", encoding="utf-8")
        _publish(ddir, "draft-skill", {"hi.sh": "echo DRAFT-RAN\n"})
        _publish(sdir, "alpha-skill-evil", {"x.sh": "echo SIBLING-RAN\n"})

        with pytest.raises(RuntimeError, match="escapes"):
            run_script("alpha-skill", bad)

    def test_nul_in_script_path_is_a_runtime_error(self, sandbox_env):
        """Contract: EVERY refusal is a RuntimeError — Path.resolve raises ValueError."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})

        with pytest.raises(RuntimeError, match="not a usable path"):
            run_script("alpha-skill", "hi.sh\x00")

    def test_unstartable_interpreter_is_a_runtime_error(self, sandbox_env, monkeypatch):
        """Contract: an interpreter/isolator missing from the child's minimal PATH makes
        Popen raise FileNotFoundError; it must surface as a RuntimeError refusal."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        monkeypatch.setattr(
            "agenticops.config.settings.skills_sandbox_interpreters",
            {".sh": "aiops-no-such-interpreter"}, raising=False,
        )

        with pytest.raises(RuntimeError, match="could not start"):
            run_script("alpha-skill", "hi.sh")

    def test_unreadable_script_is_a_runtime_error(self, sandbox_env):
        """Contract: a packaged script we cannot read (a zip/URL import can carry mode 000)
        is a refusal — shutil.copy2's PermissionError must not escape as itself."""
        import os

        from agenticops.skills.sandbox import run_script

        if os.geteuid() == 0:
            pytest.skip("root bypasses file permissions, so mode 000 is readable")

        sdir, _ddir = sandbox_env
        skill = _publish(sdir, "alpha-skill", {"noread.py": "print('hi')\n"})
        os.chmod(skill / "noread.py", 0o000)
        try:
            with pytest.raises(RuntimeError, match="could not stage"):
                run_script("alpha-skill", "noread.py")
        finally:
            os.chmod(skill / "noread.py", 0o644)     # so tmp_path cleanup can remove it

    def test_overlong_script_name_is_a_runtime_error(self, sandbox_env):
        """Contract: a path component the OS refuses (ENAMETOOLONG) is a refusal. resolve()
        tolerates it, so the OSError comes from the is_file() stat — which is why that call
        belongs INSIDE the same try block, not one line outside it."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})

        with pytest.raises(RuntimeError, match="not a usable path"):
            run_script("alpha-skill", "z" * 5000 + ".py")

    def test_lone_surrogate_stdin_is_a_runtime_error(self, sandbox_env):
        """Contract: stdin_text that will not encode is a refusal of the CALL. Task 8 feeds
        this from model-generated text, so a lone surrogate is not theoretical."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"cat.py": "import sys\nsys.stdin.read()\n"})

        with pytest.raises(RuntimeError, match="not encodable as UTF-8"):
            run_script("alpha-skill", "cat.py", stdin_text="\ud800")

    @pytest.mark.parametrize("kwargs, expect", [
        ({"script": None}, "must be strings"),
        ({"script": 123}, "must be strings"),
        ({"script": ["hi.sh"]}, "must be strings"),
        ({"skill_name": 123}, "must be strings"),
        ({"stdin_text": 123}, "stdin_text must be a string"),
        ({"args": 5}, "args must be a list of strings"),
        ({"args": [1, 2]}, "args must be a list of strings"),
        ({"args": "abc"}, "args must be a list of strings"),
    ])
    def test_wrong_argument_types_are_refusals(self, sandbox_env, kwargs, expect):
        """Contract hygiene rather than a boundary: Task 8's @tool is pydantic-validated
        against four concrete `str` annotations, so a model cannot send these. A non-agent
        caller (REST, CLI, scheduler with parsed JSON) has no such gate, and each of these
        escaped as a bare TypeError/AttributeError — or, for `args='abc'`, silently splatted
        into three single-character arguments instead of refusing.
        """
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        call = {"skill_name": "alpha-skill", "script": "hi.sh", **kwargs}

        with pytest.raises(RuntimeError, match=expect):
            run_script(**call)

    def test_non_allowlisted_suffix_refused(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"tool.rb": "puts 1\n"})

        with pytest.raises(RuntimeError, match="not allowed"):
            run_script("alpha-skill", "tool.rb")

    def test_bad_skill_name_refused(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        with pytest.raises(RuntimeError, match="invalid skill name"):
            run_script("../evil", "hi.sh")

    def test_missing_isolator_refuses_when_required(self, sandbox_env, monkeypatch):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_require_isolation", True, raising=False)

        with pytest.raises(RuntimeError, match="no network isolator"):
            run_script("alpha-skill", "hi.sh")

    def test_isolation_field_reports_truthfully(self, sandbox_env, monkeypatch):
        """打桩隔离器可用 → 字段如实报告（_wrap 打成 identity 以保持跨平台）。"""
        from agenticops.skills import sandbox

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        monkeypatch.setattr(sandbox, "detect_isolation", lambda: "unshare")
        monkeypatch.setattr(sandbox, "_wrap", lambda cmd, isolation: cmd)

        res = sandbox.run_script("alpha-skill", "hi.sh")
        assert res.isolation == "unshare"
        assert res.exit_code == 0


class TestSandboxExecution:
    def test_env_dict_is_exactly_three_keys(self, tmp_path):
        """结构证明（与平台无关）：交给子进程的 env 只有 PATH/HOME/LANG。"""
        from agenticops.skills.sandbox import _build_env

        env = _build_env(tmp_path)
        assert set(env) == {"PATH", "HOME", "LANG"}
        assert env["HOME"] == str(tmp_path)

    def test_env_has_no_credentials(self, sandbox_env, monkeypatch):
        """env 从空 dict 起建 → 键集合 ⊆ {PATH, HOME, LANG}，结构上不可能有 AWS_*。"""
        from agenticops.skills.sandbox import run_script

        monkeypatch.setenv("AWS_SESSION_TOKEN", "test-placeholder-not-a-real-token")
        monkeypatch.setenv("AIOPS_DATABASE_URL", "sqlite:///test.db")

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"env.py": "import os\nprint('\\n'.join(sorted(os.environ)))\n"})

        res = run_script("alpha-skill", "env.py")
        assert res.exit_code == 0, res.stderr
        keys = {k for k in res.stdout.splitlines() if k} - _PLATFORM_INJECTED
        assert keys <= {"PATH", "HOME", "LANG"}, f"unexpected env leaked: {keys}"
        for k in keys:
            assert not k.startswith(("AWS_", "AIOPS_"))
            assert "SECRET" not in k and "TOKEN" not in k

    def test_stdout_stderr_and_exit_code(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "split.sh": "echo to-out\necho to-err >&2\nexit 3\n",
        })
        res = run_script("alpha-skill", "split.sh")
        assert res.exit_code == 3
        assert "to-out" in res.stdout and "to-out" not in res.stderr
        assert "to-err" in res.stderr

    def test_args_and_stdin(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "echo.py": "import sys\nprint('ARG=' + sys.argv[1])\nprint('IN=' + sys.stdin.read().strip())\n",
        })
        res = run_script("alpha-skill", "echo.py", args=["hello"], stdin_text="piped\n")
        assert "ARG=hello" in res.stdout
        assert "IN=piped" in res.stdout

    def test_timeout_kills(self, sandbox_env, monkeypatch):
        import time

        from agenticops.skills.sandbox import run_script

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_timeout_seconds", 2, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"slow.sh": "sleep 999\n"})

        started = time.monotonic()
        res = run_script("alpha-skill", "slow.sh")
        elapsed = time.monotonic() - started
        assert res.exit_code == -1
        assert "timeout" in res.stderr.lower()
        assert elapsed < 20, f"timeout did not kill promptly ({elapsed:.1f}s)"

    def test_timeout_bounds_the_run_when_a_descendant_escapes(self, sandbox_env, monkeypatch):
        """The ship-blocker: a fork+setsid descendant keeps the pipes open, so an
        unbounded post-kill read lets the SCRIPT choose how long run_script blocks
        (measured 30.1s against a 2s timeout). Assert on WALL CLOCK, not the exit code —
        the exit code was already -1 while the call hung. The escaped grandchild survives
        by design (no cgroup, no PID namespace), so this test reaps it itself.
        """
        import os
        import signal
        import time

        from agenticops.skills import sandbox

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_timeout_seconds", 2, raising=False)
        sdir, _ddir = sandbox_env
        pidfile = sdir.parent / "escaped.pid"
        _publish(sdir, "alpha-skill", {"escape.py": ESCAPING_SCRIPT})

        started = time.monotonic()
        res = sandbox.run_script("alpha-skill", "escape.py", args=[str(pidfile)])
        elapsed = time.monotonic() - started
        try:
            # HARD-CODED on purpose. Deriving this from _KILL_GRACE_SECONDS made the pin a
            # tautology: raising the constant moved the ceiling with it, so the mutant died
            # only on the ABANDONED assertion below — after blocking for the payload's whole
            # lifetime (30s here, a day for `sleep 86400`). A bound must not be computed from
            # the thing it bounds.
            bound = 15                                       # 2s timeout + 5s grace + slack
            assert elapsed < bound, f"run_script blocked {elapsed:.1f}s against a 2s timeout"
            assert res.exit_code == -1
            # The note must not claim a clean kill when the read itself was cut short.
            assert "ABANDONED" in res.stderr and "MAY STILL BE RUNNING" in res.stderr
        finally:
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def test_interpreter_keyed_on_suffix_not_shebang(self, sandbox_env):
        """A `#!` line must NEVER pick the interpreter: that is what makes a mismatch a
        syntax error instead of an escape. Honouring the shebang would run a file the
        bundle scan parsed with Python rules under a shell, and vice versa."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "py_in_sh.sh": "#!/usr/bin/env python3\nimport sys\nprint('RAN AS PYTHON')\n",
            "sh_in_py.py": "#!/bin/bash\necho RAN AS BASH\n",
        })

        res = run_script("alpha-skill", "py_in_sh.sh")
        assert res.exit_code != 0, res.stdout
        assert "RAN AS PYTHON" not in res.stdout

        res = run_script("alpha-skill", "sh_in_py.py")
        assert res.exit_code != 0, res.stdout
        assert "RAN AS BASH" not in res.stdout

    def test_copied_script_is_not_executable(self, sandbox_env):
        """copy2 preserves the source mode, so the chmod is the only thing stopping an
        executable copy landing in the cwd."""
        import os

        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        skill = _publish(sdir, "alpha-skill", {
            "mode.py": "import os\nprint(oct(os.stat(__file__).st_mode & 0o777))\n",
        })
        os.chmod(skill / "mode.py", 0o755)          # source ships executable

        res = run_script("alpha-skill", "mode.py")
        assert res.stdout.strip() == "0o600", res.stdout

    def test_only_the_target_script_reaches_the_cwd(self, sandbox_env):
        """Packaged siblings must be absent at run time. Load-bearing: scan_skill_bundle
        does not scan .txt/.json/.yaml, so a sibling in the cwd re-opens the
        compile(open('payload.txt').read()) path."""
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "list.py": "import os\nprint(sorted(os.listdir('.')))\n",
            "helper.txt": "unscanned payload\n",
            "other.py": "print('other')\n",
        })

        res = run_script("alpha-skill", "list.py")
        assert res.stdout.strip() == "['list.py']", res.stdout

    def test_flooding_output_is_bounded_in_time_and_memory(self, sandbox_env, monkeypatch):
        """The second ship-blocker: a payload that WRITES without stopping was bounded by
        neither the timeout nor the cap. communicate() buffers everything before the cap is
        applied, and TimeoutExpired's constructor then joins all of it — measured 7.4s
        against a 1s timeout and +2938 MB of peak RSS *in the service process*. Both
        assertions below fail on that code; the memory one by a factor of ~6.

        Assert on wall clock AND on peak RSS: either bound alone would let the other
        regress. The RSS bound is what pins "stop accumulating past the cap".
        """
        import time

        from agenticops.skills import sandbox

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_timeout_seconds", 1, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"flood.py": FLOODING_SCRIPT})

        rss_before = _peak_rss_mb()
        started = time.monotonic()
        res = sandbox.run_script("alpha-skill", "flood.py")
        elapsed = time.monotonic() - started
        grew = _peak_rss_mb() - rss_before

        # The documented contract, verbatim: timeout + grace, for EVERY payload shape.
        # This shape needs no grace at all (killpg lands, both pipes hit EOF at once), so
        # the measured value is ~1.0s — the bound is generous, and 7.4s still crosses it.
        assert elapsed < 1 + sandbox._KILL_GRACE_SECONDS, (
            f"flooding payload ran {elapsed:.1f}s against a 1s timeout"
        )
        assert grew < 512, f"flooding payload grew the process by {grew:.0f} MB (want O(cap))"
        assert res.exit_code == -1
        assert res.truncated is True
        from agenticops.config import settings
        assert len(res.stdout) <= settings.skills_sandbox_max_output_chars

    def test_output_survives_pipe_fds_above_fd_setsize(self, sandbox_env, spare_fds):
        """The third ship-blocker: `select.select` raises ValueError for any fd >= 1024
        (FD_SETSIZE — a compile-time constant, unrelated to RLIMIT_NOFILE, which is
        1 048 576 here, so nothing warns and no limit is exceeded). That ValueError was
        caught and turned into `break`, making pump() return False — the value that means
        'both pipes reached EOF cleanly'. Measured on the pristine code with these same
        1200 spare fds: `exit=0 stdout='' stderr='' truncated=False`, i.e. TOTAL silent
        output loss asserted as a complete run. A long-lived uvicorn process with a DB pool,
        MCP subprocesses and per-session agents crosses 1024 fds as a matter of course.
        """
        from agenticops.skills.sandbox import run_script

        assert spare_fds >= 1024, "fixture did not push fds past FD_SETSIZE"
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "say.py": (
                "import sys\n"
                "sys.stdout.write('REAL-OUTPUT-HERE')\n"
                "sys.stderr.write('REAL-ERR')\n"
            ),
        })

        res = run_script("alpha-skill", "say.py")
        assert res.exit_code == 0, res.stderr
        assert res.stdout == "REAL-OUTPUT-HERE"
        assert res.stderr == "REAL-ERR"
        assert res.truncated is False

    def test_capture_failure_surfaces_instead_of_a_clean_empty_run(
        self, sandbox_env, monkeypatch
    ):
        """An unexpected failure in OUR capture loop must never be indistinguishable from a
        quiet script. EOF-by-another-name (OSError/EBADF: the pipe was closed underneath us)
        stays a silent exit; anything else is a sandbox defect and must be visible in the
        result, because 'the script ran fine and produced nothing' is a conclusion an agent
        acts on. This is the half of G1 that made the ValueError invisible.
        """
        from agenticops.skills import sandbox

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"say.py": "print('REAL-OUTPUT-HERE')\n"})

        def boom(self, timeout):
            raise ValueError("filedescriptor out of range in select()")

        monkeypatch.setattr(sandbox._Capture, "_wait", boom)

        res = sandbox.run_script("alpha-skill", "say.py")
        assert res.stdout == ""                  # nothing was read — unavoidable
        assert res.truncated is True             # ... but it must NOT claim completeness
        assert "capture FAILED" in res.stderr
        assert "INCOMPLETE" in res.stderr

    def test_timeout_note_survives_a_stderr_flood_to_the_cap(self, sandbox_env, monkeypatch):
        """Our own note is not the child's output and must not compete for its budget. The
        note used to be appended BEFORE the cap was applied, so clipping began at
        `cap - len(note)`: a child writing cap-1 bytes to stderr and then hanging returned
        the cap in attacker-chosen text ending in a bare newline — no record that a timeout
        had killed anything, and `truncated=False` claiming nothing was dropped.
        """
        import time

        from agenticops.skills.sandbox import run_script

        cap = 2000
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", cap, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_timeout_seconds", 2, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "loud_hang.py": (
                "import sys, time\n"
                f"sys.stderr.write('q' * {cap - 1})\n"
                "sys.stderr.flush()\n"
                "time.sleep(30)\n"
            ),
        })

        started = time.monotonic()
        res = run_script("alpha-skill", "loud_hang.py")
        assert time.monotonic() - started < 15
        assert res.exit_code == -1
        assert "killed after 2s timeout" in res.stderr
        # The child's cap-1 bytes are all there AND the note is intact: the note lives
        # outside the cap, so neither one displaces the other.
        assert res.stderr.startswith("q" * (cap - 1))
        assert res.truncated is False, "nothing of the child's output was dropped"

    def test_capture_stores_at_most_the_cap(self):
        """White-box companion to the RSS assertion in the flooding test, which is the only
        end-to-end evidence for 'stop accumulating past the cap' but rests on ru_maxrss — a
        whole-process high-water mark that silently goes vacuous if anything earlier in the
        process peaks higher. This one is deterministic and host-independent: drive _Capture
        over a real pipe, write far more than the cap, and assert on the STORED bytes. No
        black-box assertion can replace it — the returned lengths are <= cap either way.
        """
        import os
        import time
        from types import SimpleNamespace

        from agenticops.skills import sandbox

        cap = 1000
        r, w = os.pipe()
        os.set_blocking(w, False)
        reader = os.fdopen(r, "rb", buffering=0)
        capture = sandbox._Capture(
            SimpleNamespace(stdout=reader, stderr=None, stdin=None), b"", cap
        )
        produced = 0
        try:
            for _ in range(8):
                try:
                    produced += os.write(w, b"A" * 65536)
                except BlockingIOError:
                    pass
                capture.pump(time.monotonic() + 0.05)      # keeps draining the pipe
            os.close(w)
            w = -1
            capture.pump(time.monotonic() + 2)             # to EOF
        finally:
            capture.close()
            if w != -1:
                os.close(w)

        stored = sum(len(chunk) for chunk in capture._out)
        assert produced > 10 * cap, f"probe only wrote {produced} bytes"
        assert stored <= cap, f"stored {stored} bytes for a cap of {cap}"
        assert capture.over_cap is True

    def test_output_exactly_at_the_cap_is_not_truncated(self, sandbox_env, monkeypatch):
        """The truncation boundary is `produced > cap`, not `>=`: output of exactly cap bytes
        had nothing dropped, so claiming truncated would be a false alarm on a complete run.
        Unpinned, `>` and `>=` were indistinguishable across the whole suite.
        """
        from agenticops.skills.sandbox import run_script

        cap = 1000
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", cap, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "exact.py": f"import sys\nsys.stdout.write('x' * {cap})\n",
        })

        res = run_script("alpha-skill", "exact.py")
        assert res.exit_code == 0, res.stderr
        assert len(res.stdout) == cap
        assert res.truncated is False

    def test_cap_counts_bytes_not_characters(self, sandbox_env, monkeypatch):
        """The cap is a BYTE budget while the setting is named `..._chars`. Bytes are what
        bounds memory, so this is correct — but it is a behaviour change worth pinning
        before the setting is ever renamed: 100 CJK characters (300 bytes) at cap=200 come
        back as 66 whole characters plus one replacement char, not as 100.
        """
        from agenticops.skills.sandbox import run_script

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", 200, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "cjk.py": "import sys\nsys.stdout.write('\\u4e2d' * 100)\n",
        })

        res = run_script("alpha-skill", "cjk.py")
        assert res.exit_code == 0, res.stderr
        assert res.stdout[:66] == "中" * 66
        assert len(res.stdout) == 67          # 198 bytes of chars + 2 bytes -> one U+FFFD
        assert res.stdout[66] == "�"
        assert res.truncated is True

    def test_non_utf8_output_succeeds_with_replacement(self, sandbox_env):
        """A run that SUCCEEDS must never raise. text=True decoded strictly, so a single
        non-UTF-8 byte on stdout raised UnicodeDecodeError (a ValueError, not a
        RuntimeError) out of run_script — a completed run reported as a crash. Honest
        scripts hit this by accident whenever they re-emit raw log bytes or a latin-1 line.
        """
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "raw.py": (
                "import sys\n"
                "sys.stdout.buffer.write(b'ok-\\xff-out')\n"
                "sys.stderr.buffer.write(b'ok-\\xfe-err')\n"
            ),
        })

        res = run_script("alpha-skill", "raw.py")
        assert res.exit_code == 0, res.stderr
        assert res.stdout == "ok-�-out"          # the bad byte is REPLACED, not fatal
        assert res.stderr == "ok-�-err"

    def test_large_output_under_the_cap_is_returned_whole(self, sandbox_env, monkeypatch):
        """The bounded reader must not truncate early: 150 KB crosses the 64 KB pipe buffer,
        so it takes several select/read rounds to collect."""
        from agenticops.skills.sandbox import run_script

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", 200_000, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"chatty.py": "import sys\nsys.stdout.write('x' * 150000)\n"})

        res = run_script("alpha-skill", "chatty.py")
        assert res.exit_code == 0, res.stderr
        assert len(res.stdout) == 150000
        assert res.truncated is False

    def test_large_stdin_while_the_child_floods_stdout_does_not_deadlock(
        self, sandbox_env, monkeypatch
    ):
        """Both pipes and stdin are driven by ONE select loop. This payload writes 256 KB to
        stdout BEFORE reading stdin, so a reader that writes all of stdin first (or reads one
        pipe to EOF first) deadlocks: both directions exceed the 64 KB pipe buffer.
        """
        from agenticops.skills.sandbox import run_script

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", 2_000_000, raising=False)
        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_timeout_seconds", 20, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {
            "both.py": (
                "import sys\n"
                "sys.stdout.write('z' * 262144)\n"
                "sys.stdout.flush()\n"
                "sys.stdout.write('|IN=' + str(len(sys.stdin.read())))\n"
            ),
        })

        res = run_script("alpha-skill", "both.py", stdin_text="y" * 262144)
        assert res.exit_code == 0, res.stderr
        assert res.stdout.endswith("|IN=262144"), res.stdout[-40:]
        assert len(res.stdout) == 262144 + len("|IN=262144")

    def test_output_truncated(self, sandbox_env, monkeypatch):
        from agenticops.skills.sandbox import run_script

        monkeypatch.setattr("agenticops.config.settings.skills_sandbox_max_output_chars", 500, raising=False)
        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"loud.py": "print('x' * 100000)\n"})

        res = run_script("alpha-skill", "loud.py")
        assert res.truncated is True
        assert len(res.stdout) <= 500

    def test_workdir_is_one_shot_and_skill_dir_untouched(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        skill = _publish(sdir, "alpha-skill", {
            "write.py": (
                "import os\n"
                "open('artifact.txt', 'w').write('x')\n"
                "print(os.getcwd())\n"
            ),
        })
        before = sorted(p.name for p in skill.iterdir())

        res = run_script("alpha-skill", "write.py")
        cwd = Path(res.stdout.strip().splitlines()[-1])
        assert not cwd.exists(), "sandbox workdir must be deleted after the run"
        assert sorted(p.name for p in skill.iterdir()) == before
        assert not (skill / "artifact.txt").exists()

    def test_duration_is_reported(self, sandbox_env):
        from agenticops.skills.sandbox import run_script

        sdir, _ddir = sandbox_env
        _publish(sdir, "alpha-skill", {"hi.sh": "echo hi\n"})
        res = run_script("alpha-skill", "hi.sh")
        assert res.duration_ms >= 0 and res.isolation == "none"


class TestDetectIsolation:
    def test_returns_a_known_value(self, monkeypatch):
        from agenticops.skills import sandbox

        monkeypatch.setattr(sandbox, "_ISOLATION_CACHE", None, raising=False)
        assert sandbox.detect_isolation() in ("unshare", "sandbox-exec", "none")

    def test_none_when_no_isolator_present(self, monkeypatch):
        from agenticops.skills import sandbox

        monkeypatch.setattr(sandbox, "_ISOLATION_CACHE", None, raising=False)
        monkeypatch.setattr(sandbox.shutil, "which", lambda _n: None)
        assert sandbox.detect_isolation() == "none"

    def test_wrap_shapes(self):
        from agenticops.skills.sandbox import _wrap

        assert _wrap(["python", "x.py"], "unshare")[:3] == ["unshare", "-n", "--"]
        wrapped = _wrap(["python", "x.py"], "sandbox-exec")
        assert wrapped[0] == "sandbox-exec" and "deny network*" in wrapped[2]
        assert _wrap(["python", "x.py"], "none") == ["python", "x.py"]
