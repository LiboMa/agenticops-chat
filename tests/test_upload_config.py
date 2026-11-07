"""Chat upload config: yaml defaults + DB overrides, validated per field and across fields (2026-11-07)."""
import logging

import pytest
import yaml

from agenticops.config import PROJECT_ROOT, ChatUploadSettings, settings

SPEC_DEFAULTS = {
    "max_files": 20, "max_file_mb": 50, "max_total_mb": 200, "allowed_extensions": None,
    "text_max_chars": 100_000, "turn_text_max_chars": 200_000, "history_text_max_chars": 20_000,
    "history_images_max": 6, "image_max_edge_px": 1568, "pdf_render_pages_max": 5,
    "native_media_max_mb": 16, "staged_ttl_hours": 24,
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.services import runtime_settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cfg.db")
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings())
    models_mod.init_db()
    runtime_settings.reset_cache()
    yield
    runtime_settings.reset_cache()


def test_defaults_without_yaml_block():
    assert ChatUploadSettings().model_dump() == SPEC_DEFAULTS


def test_yaml_block_loaded():
    data = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text())
    assert data["chat_upload"] == SPEC_DEFAULTS
    assert ChatUploadSettings(**data["chat_upload"]).model_dump() == SPEC_DEFAULTS


def test_effective_is_defaults_without_overrides(db):
    from agenticops.chat import upload_config as uc
    assert uc.effective().model_dump() == SPEC_DEFAULTS
    assert uc.overrides() == {}


def test_patch_persists_and_survives_cache_reset(db):
    from agenticops.chat import upload_config as uc
    from agenticops.models import RuntimeSetting, get_db_session
    from agenticops.services import runtime_settings
    cfg = uc.save_patch({"max_files": 7, "allowed_extensions": [".pdf", ".PNG"]}, "user:admin@x")
    assert cfg.max_files == 7 and cfg.allowed_extensions == [".pdf", ".png"]
    runtime_settings.reset_cache()
    assert uc.effective().max_files == 7
    assert uc.overrides() == {"max_files": 7, "allowed_extensions": [".pdf", ".png"]}
    with get_db_session() as s:
        row = s.get(RuntimeSetting, "chat_upload")
        assert row.updated_by == "user:admin@x" and row.updated_at is not None
    # a second patch merges with the first
    assert uc.save_patch({"max_file_mb": 10}, "user:admin@x").max_files == 7


@pytest.mark.parametrize("patch,field", [
    ({"max_files": 0}, "max_files"), ({"max_files": 51}, "max_files"), ({"max_file_mb": 201}, "max_file_mb"),
    ({"history_images_max": 21}, "history_images_max"), ({"image_max_edge_px": "big"}, "image_max_edge_px"),
    ({"no_such_field": 1}, "no_such_field"),
])
def test_patch_out_of_range_422_field_named(db, patch, field):
    from agenticops.chat import upload_config as uc
    with pytest.raises(uc.UploadConfigError) as e:
        uc.validate_patch(patch)
    assert e.value.field == field
    with pytest.raises(uc.UploadConfigError):
        uc.save_patch(patch, "user:a")
    assert uc.overrides() == {}


def test_patch_unknown_extension_refused(db):
    from agenticops.chat import upload_config as uc
    with pytest.raises(uc.UploadConfigError) as e:
        uc.validate_patch({"allowed_extensions": [".pdf", ".exe"]})
    assert e.value.field == "allowed_extensions"


def test_cross_field_total_below_file_refused(db):
    from agenticops.chat import upload_config as uc
    with pytest.raises(uc.UploadConfigError) as e:
        uc.validate_patch({"max_total_mb": 40})   # default max_file_mb is 50
    assert e.value.field == "max_total_mb"
    uc.save_patch({"max_file_mb": 10}, "user:a")
    assert uc.save_patch({"max_total_mb": 40}, "user:a").max_total_mb == 40   # fine against the stored 10


def test_stale_override_out_of_range_is_dropped_not_fatal(db, caplog):
    from agenticops.chat import upload_config as uc
    from agenticops.services import runtime_settings
    runtime_settings.put("chat_upload", {"max_file_mb": 500, "max_files": 9, "allowed_extensions": [".pdf", ".exe"]},
                         "user:a")
    with caplog.at_level(logging.WARNING, logger="agenticops.chat.upload_config"):
        cfg = uc.effective()
    assert cfg.max_file_mb == 50 and cfg.max_files == 9 and cfg.allowed_extensions == [".pdf"]
    assert "max_file_mb" in caplog.text


def test_stale_total_below_new_file_default_drops_total(db, monkeypatch):
    from agenticops.chat import upload_config as uc
    uc.save_patch({"max_total_mb": 60}, "user:a")
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings(max_file_mb=100, max_total_mb=300))
    cfg = uc.effective()
    assert cfg.max_file_mb == 100 and cfg.max_total_mb == 300


def test_reset_restores_defaults(db):
    from agenticops.chat import upload_config as uc
    uc.save_patch({"max_files": 3}, "user:a")
    assert uc.reset("user:a").max_files == 20
    assert uc.overrides() == {}


def test_upload_policy_shape(db):
    from agenticops.chat import upload_config as uc
    from agenticops.chat.attachments.types import SUPPORTED
    policy = uc.upload_policy()
    assert policy["max_files"] == 20
    assert policy["max_file_bytes"] == 50 * 1024 * 1024
    assert policy["max_total_bytes"] == 200 * 1024 * 1024
    assert policy["extensions"] == sorted(SUPPORTED)
    assert policy["kinds"][".heic"] == "image" and policy["kinds"][".xlsx"] == "office"
    uc.save_patch({"allowed_extensions": [".png", ".pdf"], "max_files": 4}, "user:a")
    policy = uc.upload_policy()
    assert policy["extensions"] == [".pdf", ".png"] and policy["max_files"] == 4
    assert set(policy["kinds"]) == {".pdf", ".png"}
