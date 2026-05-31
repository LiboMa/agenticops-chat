"""Tests for cycle③ skills autonomy config settings."""
from agenticops.config import settings


def test_skills_autonomy_config_defaults():
    assert settings.skills_autonomous_write is True
    assert settings.skills_curator_enabled is True
    assert settings.skills_draft_stale_days == 30
    assert settings.skills_draft_archive_days == 60
    assert settings.skills_security_scan_on_promote is True
