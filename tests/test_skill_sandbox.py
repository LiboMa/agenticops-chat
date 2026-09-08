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
            bound = 2 + sandbox._KILL_GRACE_SECONDS + 8      # generous headroom, still << 30s
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
