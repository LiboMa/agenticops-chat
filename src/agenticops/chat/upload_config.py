"""The chat upload limits in force: settings.yaml `chat_upload` defaults + admin overrides in the DB (2026-11-07).

Overrides are stored as one JSON object under `runtime_settings` key `chat_upload`. Every read re-validates them
field by field: a value a later yaml or release no longer accepts is dropped with a warning, never fatal. A patch is
validated strictly (unknown field, out of range, unsupported extension, a total below the per-file size → refused).
"""
import logging
from typing import Any

from pydantic import ValidationError

from agenticops.chat.attachments.types import SUPPORTED
from agenticops.config import ChatUploadSettings, settings
from agenticops.services import runtime_settings

logger = logging.getLogger(__name__)

KEY = "chat_upload"
UploadConfig = ChatUploadSettings
FIELDS = tuple(ChatUploadSettings.model_fields)
_MIB = 1024 * 1024


class UploadConfigError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def defaults() -> UploadConfig:
    return settings.chat_upload.model_copy(deep=True)


def _normalize_extensions(value: Any) -> Any:
    if isinstance(value, list):
        return [str(e).strip().lower() for e in value]
    return value


def _check_field(base: UploadConfig, field: str, value: Any) -> Any:
    """The value as stored, or UploadConfigError. Checks the field alone, against the model's own range."""
    if field not in FIELDS:
        raise UploadConfigError(field, f"Unknown setting: {field}")
    value = _normalize_extensions(value) if field == "allowed_extensions" else value
    try:
        checked = ChatUploadSettings.model_validate({**base.model_dump(), field: value})
    except ValidationError as e:
        raise UploadConfigError(field, e.errors()[0].get("msg", "invalid value")) from None
    out = getattr(checked, field)
    if field == "allowed_extensions" and out is not None:
        unknown = [e for e in out if e not in SUPPORTED]
        if unknown:
            raise UploadConfigError(field, f"Unsupported extensions: {', '.join(unknown)}")
        out = sorted(set(out))
    return out


def overrides() -> dict:
    stored = runtime_settings.get(KEY)
    return stored if isinstance(stored, dict) else {}


def effective() -> UploadConfig:
    base = defaults()
    merged = base.model_dump()
    kept: dict[str, Any] = {}
    for field, value in overrides().items():
        if field == "allowed_extensions" and isinstance(value, list):
            value = [e for e in _normalize_extensions(value) if e in SUPPORTED]
        try:
            kept[field] = _check_field(base, field, value)
        except UploadConfigError as e:
            logger.warning("chat_upload override %s=%r dropped: %s", field, value, e)
    merged.update(kept)
    if merged["max_total_mb"] < merged["max_file_mb"] and "max_total_mb" in kept:
        logger.warning("chat_upload override max_total_mb=%s dropped: below max_file_mb=%s",
                       kept["max_total_mb"], merged["max_file_mb"])
        merged["max_total_mb"] = base.max_total_mb
    if merged["max_total_mb"] < merged["max_file_mb"]:
        merged["max_total_mb"] = merged["max_file_mb"]
    return ChatUploadSettings.model_validate(merged)


def validate_patch(patch: dict) -> dict:
    """The patch as it would be stored, or UploadConfigError naming the first bad field."""
    if not isinstance(patch, dict) or not patch:
        raise UploadConfigError("", "Send at least one setting")
    current = effective()
    checked = {field: _check_field(current, field, value) for field, value in patch.items()}
    merged = {**current.model_dump(), **checked}
    if merged["max_total_mb"] < merged["max_file_mb"]:
        raise UploadConfigError("max_total_mb" if "max_total_mb" in checked else "max_file_mb",
                                "The total per message must be at least the size of one file")
    return checked


def save_patch(patch: dict, actor_key: str) -> UploadConfig:
    checked = validate_patch(patch)
    runtime_settings.put(KEY, {**overrides(), **checked}, actor_key)
    return effective()


def reset(actor_key: str) -> UploadConfig:  # noqa: ARG001 — the caller audits who reset it
    runtime_settings.delete(KEY)
    return effective()


def allowed_extensions(cfg: UploadConfig) -> list[str]:
    return sorted(SUPPORTED) if cfg.allowed_extensions is None else sorted(cfg.allowed_extensions)


def upload_policy() -> dict:
    """What the composer must know (bootstrap `upload_policy`): limits in bytes and the accepted extensions."""
    cfg = effective()
    exts = allowed_extensions(cfg)
    return {
        "max_files": cfg.max_files,
        "max_file_bytes": cfg.max_file_mb * _MIB,
        "max_total_bytes": cfg.max_total_mb * _MIB,
        "extensions": exts,
        "kinds": {e: SUPPORTED[e].kind for e in exts},
    }
