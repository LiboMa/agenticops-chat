"""Tests for cycle② memory config settings."""
from agenticops.config import settings


def test_memory_config_defaults():
    assert settings.memory_max_active == 15
    assert settings.memory_stale_days == 30
    assert settings.memory_archive_days == 60
    assert settings.memory_autonomous_write is True
    assert settings.memory_curator_enabled is True
