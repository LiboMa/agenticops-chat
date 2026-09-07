"""Skill ingestion tests — hermetic: no network, no real AWS, no cloning from the internet."""

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest


SKILL_MD = """---
name: {name}
description: {name} test skill for ingestion
---

# {name}

Read-only helper.
"""


def _make_pkg(root: Path, name: str, extra: dict[str, str] | None = None) -> Path:
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    for rel, content in (extra or {}).items():
        target = pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pkg


class TestDiscoverPackages:
    def test_finds_every_skill_md_dir_sorted(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        _make_pkg(root, "alpha-skill")
        _make_pkg(root / "nested", "beta-skill")
        _make_pkg(root / "nested" / "deeper", "gamma-skill")

        pkgs = discover_packages(root)
        assert [p.name for p in pkgs] == ["alpha-skill", "beta-skill", "gamma-skill"]

    def test_root_itself_can_be_a_package(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "single-skill"
        _make_pkg(tmp_path, "single-skill")
        assert discover_packages(root) == [root]

    def test_does_not_descend_into_a_hit(self, tmp_path):
        """技能内部的 references/SKILL.md 不得被当成第二个包（spec 测试 4）。"""
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        pkg = _make_pkg(root, "alpha-skill")
        (pkg / "references").mkdir()
        (pkg / "references" / "SKILL.md").write_text(SKILL_MD.format(name="nope"), encoding="utf-8")

        assert discover_packages(root) == [pkg]

    def test_skips_vcs_and_dot_dirs(self, tmp_path):
        from agenticops.skills.sources import discover_packages

        root = tmp_path / "repo"
        _make_pkg(root, "alpha-skill")
        _make_pkg(root / ".git", "ghost-skill")
        _make_pkg(root / "node_modules", "vendor-skill")
        _make_pkg(root / ".hidden", "hidden-skill")

        assert [p.name for p in discover_packages(root)] == ["alpha-skill"]

    def test_missing_root_returns_empty(self, tmp_path):
        from agenticops.skills.sources import discover_packages
        assert discover_packages(tmp_path / "nope") == []


@pytest.fixture
def skill_dirs(tmp_path, monkeypatch):
    """Point settings at throwaway published/draft dirs (pattern from tests/test_skills_curator.py)."""
    from agenticops.skills.loader import _invalidate_skills_cache

    sdir = tmp_path / "skills"
    ddir = sdir / "draft"
    ddir.mkdir(parents=True)
    monkeypatch.setattr("agenticops.config.settings.skills_dir", sdir, raising=False)
    monkeypatch.setattr("agenticops.config.settings.skills_draft_dir", ddir, raising=False)
    _invalidate_skills_cache()
    yield sdir, ddir
    _invalidate_skills_cache()


class TestInstallPackages:
    def test_installs_as_draft_with_provenance(self, tmp_path, skill_dirs):
        from agenticops.skills.loader import parse_frontmatter
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill", {"references/deep.md": "# deep"})

        res = install_packages(discover_packages(src), "file://src", "deadbeef")

        assert [s.name for s in res.installed] == ["alpha-skill"]
        assert res.skipped == [] and res.rejected == []
        landed = ddir / "alpha-skill"
        assert (landed / "SKILL.md").is_file()
        assert (landed / "references" / "deep.md").is_file()

        fm, _ = parse_frontmatter((landed / "SKILL.md").read_text(encoding="utf-8"))
        assert fm["created_by"] == "imported"
        assert fm["status"] == "active"
        assert fm["source_uri"] == "file://src"
        assert fm["source_ref"] == "deadbeef"
        assert fm["imported_at"]
        assert res.installed[0].files == 2
        assert res.installed[0].bytes > 0

    def test_multi_skill_repo_all_land(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        for n in ("alpha-skill", "beta-skill", "gamma-skill"):
            _make_pkg(src, n)

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert sorted(s.name for s in res.installed) == ["alpha-skill", "beta-skill", "gamma-skill"]
        for n in ("alpha-skill", "beta-skill", "gamma-skill"):
            assert (ddir / n / "SKILL.md").is_file()

    def test_names_filter_skips_the_rest(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        for n in ("alpha-skill", "beta-skill"):
            _make_pkg(src, n)

        res = install_packages(discover_packages(src), "file://src", "ref", names=["beta-skill"])
        assert [s.name for s in res.installed] == ["beta-skill"]
        assert res.skipped == [("alpha-skill", "not in requested names")]
        assert not (ddir / "alpha-skill").exists()

    def test_existing_draft_is_skipped_not_overwritten(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        (ddir / "alpha-skill").mkdir()
        (ddir / "alpha-skill" / "SKILL.md").write_text("ORIGINAL", encoding="utf-8")

        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert len(res.skipped) == 1 and res.skipped[0][0] == "alpha-skill"
        assert (ddir / "alpha-skill" / "SKILL.md").read_text(encoding="utf-8") == "ORIGINAL"

    def test_published_same_name_is_skipped(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        sdir, ddir = skill_dirs
        (sdir / "alpha-skill").mkdir(parents=True)
        (sdir / "alpha-skill" / "SKILL.md").write_text("PUBLISHED", encoding="utf-8")

        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert res.skipped[0][0] == "alpha-skill"
        assert not (ddir / "alpha-skill").exists()

    @pytest.mark.parametrize("bad_name", ["Foo Bar", "../evil", "UPPER", "double--hyphen", "x" * 200])
    def test_bad_skill_names_rejected(self, tmp_path, skill_dirs, bad_name):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = src / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "SKILL.md").write_text(
            f'---\nname: "{bad_name}"\ndescription: bad name probe\n---\n\nbody\n', encoding="utf-8"
        )

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert len(res.rejected) == 1
        assert list(ddir.iterdir()) == []

    def test_disallowed_extension_rejects_whole_package(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        (pkg / "payload.so").write_bytes(b"\x00binary")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert res.rejected[0][0] == "alpha-skill"
        assert "not allowed" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_too_many_files_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import discover_packages, install_packages

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_files", 3, raising=False)
        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        for i in range(5):
            (pkg / f"note{i}.md").write_text("x", encoding="utf-8")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "too many files" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_too_large_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import discover_packages, install_packages

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_package_bytes", 512, raising=False)
        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        (pkg / "big.txt").write_text("x" * 4096, encoding="utf-8")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "too large" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_symlink_in_package_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        secret = tmp_path / "outside.txt"
        secret.write_text("outside", encoding="utf-8")
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        os.symlink(secret, pkg / "link.txt")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "symlink" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_scripts_land_without_exec_bit(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill", {"tool.sh": "#!/bin/sh\necho hi\n"})
        os.chmod(pkg / "tool.sh", 0o755)

        install_packages(discover_packages(src), "file://src", "ref")
        mode = (ddir / "alpha-skill" / "tool.sh").stat().st_mode
        assert not (mode & 0o111), "imported scripts must not be executable"

    def test_one_bad_package_does_not_block_the_others(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "good-skill")
        bad = _make_pkg(src, "bad-skill")
        (bad / "payload.so").write_bytes(b"\x00")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert [s.name for s in res.installed] == ["good-skill"]
        assert res.rejected[0][0] == "bad-skill"
        assert (ddir / "good-skill").is_dir()

    def test_no_staging_leftovers(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        install_packages(discover_packages(src), "file://src", "ref")
        staging = ddir / ".staging"
        assert not staging.exists() or list(staging.iterdir()) == []


class TestFetchAndImport:
    def test_local_dir_source(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import import_skills

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")

        res = import_skills(str(src))
        assert [s.name for s in res.installed] == ["alpha-skill"]
        assert res.source_ref == "local-dir"
        assert (ddir / "alpha-skill" / "SKILL.md").is_file()

    def test_local_zip_source(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import import_skills

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        zpath = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.write(src / "alpha-skill" / "SKILL.md", "alpha-skill/SKILL.md")

        res = import_skills(str(zpath))
        assert [s.name for s in res.installed] == ["alpha-skill"]
        assert len(res.source_ref) == 64          # sha256 hex
        assert (ddir / "alpha-skill" / "SKILL.md").is_file()

    def test_zip_path_traversal_entry_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import _unpack, import_skills

        _sdir, _ddir = skill_dirs
        zpath = tmp_path / "evil.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("../escape/SKILL.md", SKILL_MD.format(name="escape-skill"))

        with pytest.raises(ValueError, match="unsafe archive entry"):
            import_skills(str(zpath))
        # Unpack into a dest WE own, so the side-effect assertion can actually fail:
        # import_skills unpacks inside its own mkdtemp, where an escape lands beside
        # that tempdir and never under tmp_path.
        with pytest.raises(ValueError, match="unsafe archive entry"):
            _unpack(zpath, tmp_path / "unpacked")
        assert not (tmp_path / "escape").exists()

    def test_zip_absolute_entry_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import import_skills

        zpath = tmp_path / "abs.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("/tmp/aiops-evil-skill/SKILL.md", SKILL_MD.format(name="evil-skill"))

        with pytest.raises(ValueError, match="unsafe archive entry"):
            import_skills(str(zpath))
        assert not Path("/tmp/aiops-evil-skill").exists()

    def test_zip_symlink_entry_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import import_skills

        zpath = tmp_path / "link.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            info = zipfile.ZipInfo("alpha-skill/link.txt")
            info.external_attr = (0o120777 << 16)     # symlink mode bits
            zf.writestr(info, "/etc/passwd")
            zf.writestr("alpha-skill/SKILL.md", SKILL_MD.format(name="alpha-skill"))

        with pytest.raises(ValueError, match="link/special entry"):
            import_skills(str(zpath))

    def test_zip_over_size_cap_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import import_skills

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_package_bytes", 256, raising=False)
        zpath = tmp_path / "big.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("alpha-skill/SKILL.md", SKILL_MD.format(name="alpha-skill"))
            zf.writestr("alpha-skill/big.txt", "x" * 8192)

        with pytest.raises(ValueError, match="expands beyond"):
            import_skills(str(zpath))

    def test_zip_over_file_count_rejected(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import import_skills

        monkeypatch.setattr("agenticops.config.settings.skills_import_max_files", 2, raising=False)
        zpath = tmp_path / "many.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("alpha-skill/SKILL.md", SKILL_MD.format(name="alpha-skill"))
            for i in range(4):
                zf.writestr(f"alpha-skill/note{i}.md", "x")

        with pytest.raises(ValueError, match="too many files"):
            import_skills(str(zpath))

    def test_git_repo_source(self, tmp_path, skill_dirs):
        """Hermetic: clone from a local `git init` repo, never the internet."""
        import subprocess

        from agenticops.skills.sources import import_skills

        _sdir, ddir = skill_dirs
        repo = tmp_path / "fakerepo"
        for n in ("alpha-skill", "beta-skill"):
            _make_pkg(repo, n)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)

        res = import_skills(f"git+file://{repo}")
        assert sorted(s.name for s in res.installed) == ["alpha-skill", "beta-skill"]
        assert len(res.source_ref) == 40          # git sha1
        assert (ddir / "alpha-skill" / "SKILL.md").is_file()

    def test_http_markdown_becomes_single_package(self, tmp_path, skill_dirs, monkeypatch):
        """Stub the downloader — no real network in tests."""
        from agenticops.skills import sources

        _sdir, ddir = skill_dirs
        payload = SKILL_MD.format(name="url-skill").encode("utf-8")
        monkeypatch.setattr(sources, "_download", lambda url: (payload, "text/markdown"))

        res = sources.import_skills("https://example.invalid/skills/url-skill.md")
        assert [s.name for s in res.installed] == ["url-skill"]
        assert (ddir / "url-skill" / "SKILL.md").is_file()

    def test_http_zip_archive(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills import sources

        _sdir, ddir = skill_dirs
        zpath = tmp_path / "remote.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("alpha-skill/SKILL.md", SKILL_MD.format(name="alpha-skill"))
        blob = zpath.read_bytes()
        monkeypatch.setattr(sources, "_download", lambda url: (blob, "application/zip"))

        res = sources.import_skills("https://example.invalid/bundle.zip")
        assert [s.name for s in res.installed] == ["alpha-skill"]

    def test_unsupported_uri_raises(self, skill_dirs):
        from agenticops.skills.sources import import_skills

        with pytest.raises(ValueError, match="unsupported skill source"):
            import_skills("ftp://example.invalid/x.tar")

    def test_no_skill_md_in_source_raises(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import import_skills

        empty = tmp_path / "empty"
        (empty / "docs").mkdir(parents=True)
        (empty / "docs" / "readme.md").write_text("nothing here", encoding="utf-8")

        with pytest.raises(ValueError, match="no SKILL.md"):
            import_skills(str(empty))

    def test_import_disabled_refuses(self, tmp_path, skill_dirs, monkeypatch):
        from agenticops.skills.sources import import_skills

        monkeypatch.setattr("agenticops.config.settings.skills_import_enabled", False, raising=False)
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        with pytest.raises(RuntimeError, match="disabled"):
            import_skills(str(src))

    def test_import_never_executes_packaged_scripts(self, tmp_path, skill_dirs):
        """spec 测试 9：install.sh 会写标记文件；导入后标记文件必须不存在。"""
        from agenticops.skills.sources import import_skills

        _sdir, ddir = skill_dirs
        marker = tmp_path / "EXECUTED"
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill", {"install.sh": f"#!/bin/sh\ntouch {marker}\n"})

        import_skills(str(src))
        assert not marker.exists(), "import must never execute packaged scripts"
        assert (ddir / "alpha-skill" / "install.sh").is_file()

    def test_hardlink_in_package_rejected(self, tmp_path, skill_dirs):
        """A hard link passes the symlink/escape checks but still copies foreign bytes."""
        from agenticops.skills.sources import discover_packages, install_packages

        _sdir, ddir = skill_dirs
        outside = tmp_path / "outside.txt"
        outside.write_text("outside content", encoding="utf-8")
        src = tmp_path / "src"
        pkg = _make_pkg(src, "alpha-skill")
        os.link(outside, pkg / "notes.md")

        res = install_packages(discover_packages(src), "file://src", "ref")
        assert res.installed == []
        assert "hard link" in res.rejected[0][1]
        assert not (ddir / "alpha-skill").exists()

    def test_local_targz_source(self, tmp_path, skill_dirs):
        """.tar.gz is an accepted source and the fallback for any archive-ish Content-Type."""
        from agenticops.skills.sources import import_skills

        _sdir, ddir = skill_dirs
        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        tpath = tmp_path / "bundle.tar.gz"
        with tarfile.open(tpath, "w:gz") as tf:
            tf.add(src / "alpha-skill" / "SKILL.md", arcname="alpha-skill/SKILL.md")

        res = import_skills(str(tpath))
        assert [s.name for s in res.installed] == ["alpha-skill"]
        assert len(res.source_ref) == 64          # sha256 hex
        assert (ddir / "alpha-skill" / "SKILL.md").is_file()

    def test_targz_path_traversal_entry_rejected(self, tmp_path, skill_dirs):
        from agenticops.skills.sources import _unpack, import_skills

        tpath = tmp_path / "evil.tar.gz"
        payload = SKILL_MD.format(name="escape-skill").encode("utf-8")
        with tarfile.open(tpath, "w:gz") as tf:
            info = tarfile.TarInfo("../escape/SKILL.md")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

        with pytest.raises(ValueError, match="unsafe archive entry"):
            import_skills(str(tpath))
        # Same reasoning as the zip case: unpack into a dest we own so this can fail.
        with pytest.raises(ValueError, match="unsafe archive entry"):
            _unpack(tpath, tmp_path / "unpacked")
        assert not (tmp_path / "escape").exists()

    def test_targz_symlink_member_rejected(self, tmp_path, skill_dirs):
        """`not m.isreg()` is the tar branch's only link/special defense — pin it."""
        from agenticops.skills.sources import import_skills

        tpath = tmp_path / "link.tar.gz"
        with tarfile.open(tpath, "w:gz") as tf:
            info = tarfile.TarInfo("alpha-skill/link.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "other.txt"
            tf.addfile(info)
            body = SKILL_MD.format(name="alpha-skill").encode("utf-8")
            md = tarfile.TarInfo("alpha-skill/SKILL.md")
            md.size = len(body)
            tf.addfile(md, io.BytesIO(body))

        with pytest.raises(ValueError, match="link/special entry"):
            import_skills(str(tpath))

    def test_corrupt_archive_raises_valueerror(self, tmp_path, skill_dirs):
        """zipfile/tarfile errors must surface as ValueError (HTTP 400), never a 500."""
        from agenticops.skills.sources import import_skills

        bad = tmp_path / "broken.zip"
        bad.write_bytes(b"not a zip at all")

        with pytest.raises(ValueError) as excinfo:
            import_skills(str(bad))
        assert str(excinfo.value)

    def test_corrupt_deflate_stream_raises_valueerror(self, tmp_path, skill_dirs):
        """zlib.error inherits from Exception, so it slips past ValueError AND OSError.

        `b"not a zip"` dies at the header (BadZipFile) and never reaches the
        decompressor, which is why the other corrupt-archive test misses this.
        Deterministic by construction: the whole deflate payload is overwritten with
        0xff (length preserved, so every header/offset stays valid), which always
        fails inflate rather than depending on a lucky bit-flip offset.
        """
        import struct

        from agenticops.skills.sources import import_skills

        zpath = tmp_path / "deflate.zip"
        body = SKILL_MD.format(name="alpha-skill").encode("utf-8") * 8
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("alpha-skill/SKILL.md", body)
        with zipfile.ZipFile(zpath) as zf:
            info = zf.infolist()[0]

        raw = bytearray(zpath.read_bytes())
        # local file header: 30 fixed bytes, then the name, then the extra field
        name_len, extra_len = struct.unpack("<HH", raw[info.header_offset + 26:info.header_offset + 30])
        start = info.header_offset + 30 + name_len + extra_len
        raw[start:start + info.compress_size] = b"\xff" * info.compress_size
        zpath.write_bytes(bytes(raw))

        with pytest.raises(ValueError, match="cannot unpack archive"):
            import_skills(str(zpath))

    def test_download_network_error_raises_valueerror(self, monkeypatch):
        """A dead/typo'd URL is a bad source (400), not a server fault (500)."""
        import urllib.error

        from agenticops.skills import sources

        def boom(*a, **kw):
            raise urllib.error.URLError("nope")

        monkeypatch.setattr(sources.urllib.request, "urlopen", boom)
        with pytest.raises(ValueError, match="download failed"):
            sources._download("https://example.invalid/x.md")

    def test_nul_in_entry_name_rejected(self):
        from agenticops.skills import sources

        with pytest.raises(ValueError, match="unsafe archive entry"):
            sources._check_entry_name("a\x00b")

    def test_download_byte_cap_enforced(self, monkeypatch):
        """The streaming cap loop — every other http test stubs _download away."""
        from agenticops.skills import sources

        monkeypatch.setattr(
            "agenticops.config.settings.skills_import_max_package_bytes", 1024, raising=False
        )

        class _Resp:
            headers = {"Content-Type": "application/zip"}

            def __init__(self):
                self.left = 8

            def read(self, n):
                if self.left <= 0:
                    return b""
                self.left -= 1
                return b"x" * 512

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **kw: _Resp())
        with pytest.raises(ValueError, match="exceeds"):
            sources._download("https://example.invalid/big.zip")

    def test_download_parses_content_type(self, monkeypatch):
        from agenticops.skills import sources

        body = b"# hello\n"

        class _Resp:
            headers = {"Content-Type": "text/markdown; charset=utf-8"}

            def __init__(self):
                self.done = False

            def read(self, n):
                if self.done:
                    return b""
                self.done = True
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **kw: _Resp())
        assert sources._download("https://example.invalid/x.md") == (body, "text/markdown")

    def test_git_subdir_traversal_rejected(self, tmp_path, skill_dirs):
        """`#subdir` must never resolve outside the clone. Hermetic local repo."""
        import subprocess

        from agenticops.skills.sources import import_skills

        repo = tmp_path / "subdirrepo"
        _make_pkg(repo, "alpha-skill")
        os.symlink(tmp_path / "outside", repo / "outside-link")
        (tmp_path / "outside").mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)

        # normpath collapses any `..`, so the entry-name guard fires first here.
        with pytest.raises(ValueError, match="unsafe archive entry"):
            import_skills(f"git+file://{repo}#../../etc")
        # A subdir that survives normalization but is not a directory in the clone.
        with pytest.raises(ValueError, match="subdir not found"):
            import_skills(f"git+file://{repo}#nope")
        # A committed symlink resolving outside the clone — the resolved-prefix check.
        with pytest.raises(ValueError, match="subdir not found"):
            import_skills(f"git+file://{repo}#outside-link")

    def test_git_ext_transport_rejected(self, tmp_path, skill_dirs):
        """`ext::<cmd>` is git's transport-helper form — it runs <cmd>. Must never reach git."""
        from agenticops.skills.sources import import_skills

        marker = tmp_path / "pwn-marker"
        # Match OUR message, not git's own "fatal: transport 'ext' not allowed" —
        # a bare "transport" would let this pass with layer 1a deleted.
        with pytest.raises(ValueError, match="unsupported git transport"):
            import_skills(f"git+ext::touch {marker}")
        assert not marker.exists(), "ext:: transport executed a command"

    def test_git_ext_transport_rejected_even_with_git_allow_protocol_env(
        self, tmp_path, skill_dirs, monkeypatch
    ):
        """GIT_ALLOW_PROTOCOL overrides git's own config refusal — our allowlist must not depend on it."""
        from agenticops.skills.sources import import_skills

        monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "ext")
        marker = tmp_path / "pwn-marker"
        with pytest.raises(ValueError, match="unsupported git transport"):
            import_skills(f"git+ext::touch {marker}")
        assert not marker.exists(), "ext:: transport executed a command"

    def test_git_url_starting_with_dash_rejected(self, tmp_path, skill_dirs):
        """A leading `-` could be read as a git option (e.g. --upload-pack=<cmd>)."""
        from agenticops.skills.sources import import_skills

        marker = tmp_path / "pwn-marker"
        with pytest.raises(ValueError, match="unsupported git transport"):
            import_skills(f"git+--upload-pack=touch {marker}")
        assert not marker.exists(), "option-shaped git url executed a command"

    def test_git_scp_style_option_shaped_host_rejected(self):
        """git blocks an option-shaped `ssh://` host but NOT an option-shaped scp host."""
        from agenticops.skills.sources import _validate_git_url

        with pytest.raises(ValueError, match="unsupported git transport"):
            _validate_git_url("git@-oProxyCommand:x/y")

    def test_git_overlong_url_raises_valueerror_not_oserror(self, tmp_path, skill_dirs):
        """Path.exists() re-raises ENAMETOOLONG; that must not escape as OSError (HTTP 500)."""
        from agenticops.skills.sources import import_skills

        with pytest.raises(ValueError, match="unsupported git transport"):
            import_skills("git+" + "a" * 300)

    def test_git_scp_style_url_is_accepted_by_the_allowlist(self):
        """The allowlist must not reject the legitimate scp-style form."""
        from agenticops.skills.sources import _validate_git_url

        _validate_git_url("git@github.com:owner/repo.git")

    def test_git_clone_pins_transport_config_and_sanitizes_env(self, tmp_path, monkeypatch):
        """Depth layers behind the allowlist: `-c protocol.ext.allow=never` + stripped env."""
        from agenticops.skills import sources

        monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "ext")
        monkeypatch.setenv("GIT_PROTOCOL_FROM_USER", "1")
        seen: dict[str, object] = {}

        def spy(cmd, **kw):
            seen["cmd"] = cmd
            seen["env"] = kw.get("env")
            raise AssertionError("stop before any real clone")

        monkeypatch.setattr(sources.subprocess, "run", spy)
        with pytest.raises(AssertionError):
            sources._fetch_git(f"git+file://{tmp_path}", tmp_path / "wd")

        cmd = seen["cmd"]
        assert cmd[:3] == ["git", "-c", "protocol.ext.allow=never"], cmd
        assert cmd[3] == "clone"
        env = seen["env"]
        assert "GIT_ALLOW_PROTOCOL" not in env
        assert "GIT_PROTOCOL_FROM_USER" not in env
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env.get("PATH"), "git still needs PATH — this is ingestion, not the sandbox"

    def test_tempdir_cleaned_on_success_and_failure(self, tmp_path, skill_dirs, monkeypatch):
        import tempfile

        from agenticops.skills.sources import import_skills

        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a, **kw):
            d = real_mkdtemp(*a, **kw)
            created.append(d)
            return d

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        src = tmp_path / "src"
        _make_pkg(src, "alpha-skill")
        import_skills(str(src))
        with pytest.raises(ValueError):
            import_skills("ftp://example.invalid/x")

        assert created, "expected import to use a temp workdir"
        for d in created:
            assert not Path(d).exists(), f"temp workdir leaked: {d}"
