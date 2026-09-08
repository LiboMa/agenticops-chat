"""Tests for cycle③ skills autonomy config settings."""
from agenticops.config import settings


def test_skills_autonomy_config_defaults():
    assert settings.skills_autonomous_write is True
    assert settings.skills_curator_enabled is True
    assert settings.skills_draft_stale_days == 30
    assert settings.skills_draft_archive_days == 60
    assert settings.skills_security_scan_on_promote is True


class TestSkillImportSandboxConfig:
    """MVP: skill wide-loading + script sandbox config surface."""

    def test_import_defaults(self):
        from agenticops.config import settings
        assert settings.skills_import_enabled is True
        assert settings.skills_import_max_package_bytes == 2097152
        assert settings.skills_import_max_files == 50
        assert settings.skills_import_timeout_seconds == 60
        assert ".md" in settings.skills_import_allowed_extensions
        assert ".py" in settings.skills_import_allowed_extensions
        assert ".sh" in settings.skills_import_allowed_extensions
        # 可执行/二进制类后缀必须不在白名单
        for bad in (".so", ".dylib", ".exe", ".bin"):
            assert bad not in settings.skills_import_allowed_extensions

    def test_sandbox_defaults_are_closed(self):
        from agenticops.config import settings
        # 新执行通道默认关闭，且默认拒绝无隔离运行
        assert settings.skills_sandbox_enabled is False
        assert settings.skills_sandbox_require_isolation is True
        assert settings.skills_sandbox_timeout_seconds == 60
        assert settings.skills_sandbox_max_output_bytes == 20000
        assert settings.skills_sandbox_interpreters[".py"] == "python"
        assert settings.skills_sandbox_interpreters[".sh"] == "/bin/bash"

    def test_yaml_carries_the_values_not_only_the_schema(self):
        """CLAUDE.md 铁律：默认值必须落在 settings.yaml，config.py 只有 schema。"""
        import yaml
        from agenticops.config import PROJECT_ROOT
        data = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
        for key in (
            "skills_import_enabled",
            "skills_import_max_package_bytes",
            "skills_import_max_files",
            "skills_import_allowed_extensions",
            "skills_import_timeout_seconds",
            "skills_sandbox_enabled",
            "skills_sandbox_timeout_seconds",
            "skills_sandbox_max_output_bytes",
            "skills_sandbox_require_isolation",
            "skills_sandbox_interpreters",
        ):
            assert key in data, f"{key} missing from config/settings.yaml"
            # Presence alone would pass with a WRONG value in the YAML — the point of the
            # rule is that the YAML is the source of truth, so pin the value too.
            assert data[key] == getattr(settings, key), (
                f"{key}: settings.yaml has {data[key]!r} but settings resolves to "
                f"{getattr(settings, key)!r}"
            )
