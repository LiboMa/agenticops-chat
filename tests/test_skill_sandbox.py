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

        with pytest.raises(RuntimeError, match="draft"):
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
