"""Model connection settings in force (2026-11-08): settings.yaml `model_runtime` defaults + admin overrides in the DB.

Same shape as `chat/upload_config`: overrides are one JSON object under `runtime_settings` key `model_runtime`; every
read re-validates them field by field (a value a later yaml or release no longer accepts is dropped with a warning,
never fatal); a patch is validated strictly (unknown field or out of range → refused). Read at every agent build
(`preamble.bedrock_model_kwargs`), so a change applies to the next agent built.
"""
import logging
from typing import Any

from pydantic import ValidationError

from agenticops.config import ModelRuntimeSettings, settings
from agenticops.services import runtime_settings

logger = logging.getLogger(__name__)

KEY = "model_runtime"
FIELDS = tuple(ModelRuntimeSettings.model_fields)


class ModelRuntimeError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def defaults() -> ModelRuntimeSettings:
    return settings.model_runtime.model_copy(deep=True)


def _check_field(base: ModelRuntimeSettings, field: str, value: Any) -> Any:
    if field not in FIELDS:
        raise ModelRuntimeError(field, f"Unknown setting: {field}")
    try:
        checked = ModelRuntimeSettings.model_validate({**base.model_dump(), field: value})
    except ValidationError as e:
        raise ModelRuntimeError(field, e.errors()[0].get("msg", "invalid value")) from None
    return getattr(checked, field)


def overrides() -> dict:
    stored = runtime_settings.get(KEY)
    return stored if isinstance(stored, dict) else {}


def effective() -> ModelRuntimeSettings:
    base = defaults()
    merged = base.model_dump()
    for field, value in overrides().items():
        try:
            merged[field] = _check_field(base, field, value)
        except ModelRuntimeError as e:
            logger.warning("model_runtime override %s=%r dropped: %s", field, value, e)
    return ModelRuntimeSettings.model_validate(merged)


def validate_patch(patch: dict) -> dict:
    """The patch as it would be stored, or ModelRuntimeError naming the first bad field."""
    if not isinstance(patch, dict) or not patch:
        raise ModelRuntimeError("", "Send at least one setting")
    current = effective()
    return {field: _check_field(current, field, value) for field, value in patch.items()}


def save_patch(patch: dict, actor_key: str) -> ModelRuntimeSettings:
    checked = validate_patch(patch)
    runtime_settings.put(KEY, {**overrides(), **checked}, actor_key)
    return effective()


def reset(actor_key: str) -> ModelRuntimeSettings:  # noqa: ARG001 — the caller audits who reset it
    runtime_settings.delete(KEY)
    return effective()
