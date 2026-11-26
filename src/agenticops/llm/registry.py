"""The model providers an admin added, and the Bedrock switch (MVP-2.9.0 N35).

- A provider's API key and extra request headers are encrypted by the credential store and never leave this module
  except through `get()` (the in-process config the model factory builds clients from). `list_public()` — what the
  API and the CLI show — says only whether a key is stored.
- An edit merges like an account edit (credentials/store.merge_credentials): an empty value or an echoed mask keeps the
  stored key, a new value replaces it, `clear_api_key` removes it. The name never changes.
- A provider (or one of its models) that a setting uses cannot be deleted or turned off: `in_use`, naming the settings.
- Every write — and the Bedrock switch — writes one `audit_logs` row in the same transaction: the plain fields before
  and after and what happened to the key (`details.key_change` = added / replaced / kept / removed / none — not under
  a key named like a secret, which the DB scrubber would mask), never the key.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from agenticops.llm.presets import KINDS, PRESETS
from agenticops.llm.refs import NAME_RE, RESERVED, parse_ref

ENTITY = "model_provider"
RUNTIME_KEY = "model_providers"
_MASK_PREFIX = "****"
# stored under a name the credential store treats as sensitive, so header values are encrypted with the key
_HEADERS = "header_secrets"


class ProviderError(Exception):
    """A refused change: the HTTP status, a stable code the page words, a sentence, and extra fields (refs)."""

    def __init__(self, status: int, code: str, detail: str, extra: Optional[dict] = None):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail
        self.extra = extra or {}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    display_name: str
    kind: str
    preset: str
    base_url: str
    api_key: str
    extra_headers: dict = field(default_factory=dict)
    timeout_seconds: int = 60
    enabled: bool = True


_cache: dict[str, Optional[ProviderConfig]] = {}
_lock = threading.Lock()


def reset_cache() -> None:
    with _lock:
        _cache.clear()


# ── validation ────────────────────────────────────────────────────────────────

def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ProviderError(422, "invalid_name",
                            "a provider name is 2–32 characters: lowercase letters, digits and «-», starting with a letter")
    if name in RESERVED:
        raise ProviderError(422, "reserved_name", f"«{name}» is the built-in provider")
    return name


def _check_base_url(url: Any) -> str:
    text = (url or "").strip() if isinstance(url, str) else ""
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ProviderError(422, "invalid_base_url", "the address must start with http:// or https:// and name a host")
    return text.rstrip("/")


def _check_timeout(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = -1
    if not 5 <= n <= 600:
        raise ProviderError(422, "invalid_timeout", "the timeout is 5–600 seconds")
    return n


def _printable(text: str) -> bool:
    """Printable ASCII only: an HTTP header can carry nothing else, and the HTTP library's refusal of anything else
    quotes the whole value — a key — in its error (final review)."""
    return all(" " <= ch <= "~" for ch in text)


def _check_key(value: str) -> str:
    if not _printable(value):
        raise ProviderError(422, "invalid_key", "an API key is printable ASCII only — no spaces inside, line breaks or tabs")
    return value


def _check_headers(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str)
                                              and _printable(k) and _printable(v) for k, v in value.items()):
        raise ProviderError(422, "invalid_headers", "extra headers are name → text pairs of printable ASCII")
    return {k.strip(): v for k, v in value.items()}


# ── storage ───────────────────────────────────────────────────────────────────

def _store():
    from agenticops.credentials.store import get_credential_store
    return get_credential_store()


def _plain_secrets(row) -> dict:
    return _store().decrypt_credentials(dict(row.secrets or {})) if row.secrets else {}


def _snapshot(row) -> dict:
    """The plain fields of a row, for audit rows and lists — never the key or the header values."""
    secrets = _plain_secrets(row)
    return {"name": row.name, "display_name": row.display_name, "kind": row.kind, "preset": row.preset,
            "base_url": row.base_url, "timeout_seconds": row.timeout_seconds, "enabled": bool(row.enabled),
            "header_names": sorted((secrets.get(_HEADERS) or {}).keys())}


def _key_change(had: bool, has: bool, replaced: bool) -> str:
    if replaced:
        return "replaced" if had else "added"
    if had and not has:
        return "removed"
    return "kept" if had else "none"


def _audit(session, action: str, name: str, actor, *, before=None, after=None, details=None) -> None:
    from agenticops.audit.service import AuditService
    AuditService.log(action, ENTITY, name, entity_name=name, actor=getattr(actor, "key", None),
                     user_id=getattr(actor, "user_id", None), details=details, old_values=before,
                     new_values=after, session=session)


def _row(session, name: str):
    from agenticops.llm.models import ModelProvider
    row = session.query(ModelProvider).filter_by(name=name).first()
    if row is None:
        raise ProviderError(404, "not_found", f"no provider «{name}»")
    return row


def get(name: str) -> Optional[ProviderConfig]:
    """The provider with its key decrypted — for building clients in this process; None when there is no such row."""
    with _lock:
        if name in _cache:
            return _cache[name]
    from agenticops.llm.models import ModelProvider
    from agenticops.models import get_db_session
    with get_db_session() as s:
        row = s.query(ModelProvider).filter_by(name=name).first()
        cfg = None
        if row is not None:
            secrets = _plain_secrets(row)
            cfg = ProviderConfig(name=row.name, display_name=row.display_name or row.name, kind=row.kind,
                                 preset=row.preset, base_url=row.base_url, api_key=secrets.get("api_key") or "",
                                 extra_headers=dict(secrets.get(_HEADERS) or {}),
                                 timeout_seconds=int(row.timeout_seconds or 60), enabled=bool(row.enabled))
    with _lock:
        _cache[name] = cfg
    return cfg


def list_public() -> list[dict]:
    from agenticops.llm.models import ModelProvider, ProviderModel
    from agenticops.models import get_db_session
    out = []
    with get_db_session() as s:
        for row in s.query(ModelProvider).order_by(ModelProvider.name):
            secrets = _plain_secrets(row)
            count = s.query(ProviderModel).filter_by(provider=row.name).count()
            out.append({**_snapshot(row), "has_api_key": bool(secrets.get("api_key")), "models_count": count,
                        "last_test": row.last_test, "references": references(row.name),
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                        "updated_by": row.updated_by})
    return out


def create(data: dict, actor) -> dict:
    from agenticops.llm.models import ModelProvider
    from agenticops.models import get_db_session
    name = _check_name(data.get("name"))
    preset_key = data.get("preset") or ("custom_anthropic" if data.get("kind") == "anthropic_compatible" else "custom_openai")
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise ProviderError(422, "invalid_preset", f"no preset «{preset_key}»")
    kind = data.get("kind") or preset.kind
    if kind not in KINDS:
        raise ProviderError(422, "invalid_kind", "the protocol is openai_compatible or anthropic_compatible")
    base_url = _check_base_url(data.get("base_url") if data.get("base_url") is not None else preset.base_url)
    timeout = _check_timeout(data.get("timeout_seconds", 60))
    headers = _check_headers(data.get("extra_headers"))
    api_key = _check_key((data.get("api_key") or "").strip())
    if api_key.startswith(_MASK_PREFIX):
        api_key = ""
    with get_db_session() as s:
        if s.query(ModelProvider).filter_by(name=name).first() is not None:
            raise ProviderError(409, "name_taken", f"a provider named «{name}» already exists")
        row = ModelProvider(name=name, display_name=(data.get("display_name") or preset.label)[:100], kind=kind,
                            preset=preset_key, base_url=base_url, timeout_seconds=timeout,
                            enabled=bool(data.get("enabled", True)), updated_by=getattr(actor, "key", None),
                            secrets=_store().encrypt_credentials({"api_key": api_key, _HEADERS: headers}))
        s.add(row)
        s.flush()
        after = _snapshot(row)
        _audit(s, "create", name, actor, after=after, details={"key_change": _key_change(False, bool(api_key), bool(api_key))})
    reset_cache()
    return {**after, "has_api_key": bool(api_key)}


def update(name: str, data: dict, actor, *, clear_api_key: bool = False) -> dict:
    from agenticops.models import get_db_session
    if "name" in data and data["name"] != name:
        raise ProviderError(422, "invalid_name", "a provider cannot be renamed — add a new one instead")
    with get_db_session() as s:
        row = _row(s, name)
        before = _snapshot(row)
        secrets = _plain_secrets(row)
        had_key = bool(secrets.get("api_key"))
        if "display_name" in data and data["display_name"] is not None:
            row.display_name = str(data["display_name"])[:100]
        if "kind" in data and data["kind"] is not None:
            if data["kind"] not in KINDS:
                raise ProviderError(422, "invalid_kind", "the protocol is openai_compatible or anthropic_compatible")
            row.kind = data["kind"]
        if "preset" in data and data["preset"] is not None:
            if data["preset"] not in PRESETS:
                raise ProviderError(422, "invalid_preset", f"no preset «{data['preset']}»")
            row.preset = data["preset"]
        if "base_url" in data and data["base_url"] is not None:
            row.base_url = _check_base_url(data["base_url"])
        if "timeout_seconds" in data and data["timeout_seconds"] is not None:
            row.timeout_seconds = _check_timeout(data["timeout_seconds"])
        if "enabled" in data and data["enabled"] is not None and bool(data["enabled"]) != bool(row.enabled):
            if not data["enabled"]:
                _refuse_in_use(name)
            row.enabled = bool(data["enabled"])
        replaced = _key_replaced(data.get("api_key"))
        secrets["api_key"] = _merged_key(secrets.get("api_key") or "", data.get("api_key"), clear_api_key)
        if "extra_headers" in data and data["extra_headers"] is not None:
            secrets[_HEADERS] = _merged_headers(secrets.get(_HEADERS) or {}, data["extra_headers"])
        row.secrets = _store().encrypt_credentials(secrets)
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = getattr(actor, "key", None)
        s.flush()
        after = _snapshot(row)
        _audit(s, "update", name, actor, before=before, after=after,
               details={"key_change": _key_change(had_key, bool(secrets.get("api_key")), replaced and not clear_api_key)})
        has_key = bool(secrets.get("api_key"))
    reset_cache()
    return {**after, "has_api_key": has_key}



def _key_replaced(new_key: Any) -> bool:
    return isinstance(new_key, str) and bool(new_key.strip()) and not new_key.strip().startswith(_MASK_PREFIX)


def _merged_key(stored: str, new_key: Any, clear: bool) -> str:
    """The key after an edit: removed on `clear`, replaced by a typed one, else the stored one (an empty field or the
    mask the list shows keeps it)."""
    if clear:
        return ""
    return _check_key(new_key.strip()) if _key_replaced(new_key) else stored


def _merged_headers(old_headers: dict, value: Any) -> dict:
    """The extra headers after an edit: a value echoed as a mask keeps the stored value of that header; a NEW header
    needs a value."""
    incoming = _check_headers(value)
    fresh = [k for k, v in incoming.items() if v.strip().startswith(_MASK_PREFIX) and k not in old_headers]
    if fresh:
        raise ProviderError(422, "invalid_headers", f"a new header needs its value: {', '.join(sorted(fresh))}")
    return {k: (old_headers[k] if v.strip().startswith(_MASK_PREFIX) else v) for k, v in incoming.items()}


def draft_config(data: dict, existing: Optional[str] = None) -> ProviderConfig:
    """The provider a form describes, checked as saving it would check it, without writing anything — for the
    connection test before a save (MVP-2.9.0 review). `existing` = the stored provider an edit starts from: the form
    is laid over it the way `update` lays it (an empty or masked key keeps the stored one, masked header values keep
    theirs, `clear_api_key` removes the key)."""
    if existing:
        cfg = get(existing)
        if cfg is None:
            raise ProviderError(404, "not_found", f"no provider «{existing}»")
        kind = data.get("kind") or cfg.kind
        if kind not in KINDS:
            raise ProviderError(422, "invalid_kind", "the protocol is openai_compatible or anthropic_compatible")
        base_url = _check_base_url(data["base_url"]) if data.get("base_url") is not None else cfg.base_url
        timeout = _check_timeout(data["timeout_seconds"]) if data.get("timeout_seconds") is not None else cfg.timeout_seconds
        headers = (_merged_headers(cfg.extra_headers, data["extra_headers"]) if data.get("extra_headers") is not None
                   else dict(cfg.extra_headers))
        return ProviderConfig(name=cfg.name, display_name=cfg.display_name, kind=kind, preset=cfg.preset,
                              base_url=base_url, api_key=_merged_key(cfg.api_key, data.get("api_key"),
                                                                     bool(data.get("clear_api_key"))),
                              extra_headers=headers, timeout_seconds=timeout, enabled=cfg.enabled)
    name = _check_name(data.get("name"))
    preset_key = data.get("preset") or ("custom_anthropic" if data.get("kind") == "anthropic_compatible" else "custom_openai")
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise ProviderError(422, "invalid_preset", f"no preset «{preset_key}»")
    kind = data.get("kind") or preset.kind
    if kind not in KINDS:
        raise ProviderError(422, "invalid_kind", "the protocol is openai_compatible or anthropic_compatible")
    base_url = _check_base_url(data.get("base_url") if data.get("base_url") is not None else preset.base_url)
    timeout = _check_timeout(data.get("timeout_seconds", 60))
    headers = _check_headers(data.get("extra_headers"))
    api_key = _check_key((data.get("api_key") or "").strip())
    if api_key.startswith(_MASK_PREFIX):
        api_key = ""
    from agenticops.llm.models import ModelProvider
    from agenticops.models import get_db_session
    with get_db_session() as s:
        if s.query(ModelProvider).filter_by(name=name).first() is not None:
            raise ProviderError(409, "name_taken", f"a provider named «{name}» already exists")
    return ProviderConfig(name=name, display_name=data.get("display_name") or name, kind=kind, preset=preset_key,
                          base_url=base_url, api_key=api_key, extra_headers=headers, timeout_seconds=timeout)


def set_enabled(name: str, enabled: bool, actor) -> dict:
    return update(name, {"enabled": bool(enabled)}, actor)


def delete(name: str, actor) -> None:
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    _refuse_in_use(name)
    with get_db_session() as s:
        row = _row(s, name)
        before = _snapshot(row)
        had_key = bool(_plain_secrets(row).get("api_key"))
        s.query(ProviderModel).filter_by(provider=name).delete(synchronize_session=False)
        s.delete(row)
        _audit(s, "delete", name, actor, before=before, details={"key_change": "removed" if had_key else "none"})
    reset_cache()


# ── what uses a provider ──────────────────────────────────────────────────────

# the settings that hold a model reference, in the order they are reported
AGENT_MODEL_FIELDS = tuple(f"agent_{a}_model_id" for a in ("main", "scan", "detect", "rca", "sre", "executor", "reporter"))
TIER_FIELDS = ("bedrock_model_id", "bedrock_model_id_cheap", "bedrock_model_id_strong")
CHEAP_DEFAULT_FIELDS = ("galaxy_model_id", "security_model_id", "report_translation_model_id",
                        "signal_gate_llm_model", "rca_critic_model_id")
MODEL_SETTING_FIELDS = AGENT_MODEL_FIELDS + TIER_FIELDS + ("executor_simple_model_id",) + CHEAP_DEFAULT_FIELDS
EMBEDDING_FIELD = "embedding_model_ref"


def _raw(field_name: str) -> str:
    from agenticops.config import settings
    if field_name == EMBEDDING_FIELD:
        from agenticops.services import runtime_settings
        stored = runtime_settings.get("embedding")
        if isinstance(stored, dict) and isinstance(stored.get("model_ref"), str):
            return stored["model_ref"]
    return str(getattr(settings, field_name, "") or "")


def effective_value(field_name: str) -> str:
    """What a model setting resolves to: its own value, or the default it falls back to when empty."""
    from agenticops.config import get_agent_model_config, settings
    raw = _raw(field_name)
    if raw:
        return raw
    if field_name in AGENT_MODEL_FIELDS:
        return get_agent_model_config(field_name[len("agent_"):-len("_model_id")])[0]
    if field_name in CHEAP_DEFAULT_FIELDS:
        return str(settings.bedrock_model_id_cheap or "")
    return ""


def references(provider: str, model_id: Optional[str] = None) -> list[str]:
    """The settings whose OWN value is a reference to this provider (and model) — the ones to change before it can go."""
    out = []
    for f in MODEL_SETTING_FIELDS + (EMBEDDING_FIELD,):
        raw = _raw(f)
        if not raw:
            continue
        try:
            ref = parse_ref(raw)
        except ValueError:
            continue
        if ref.provider == provider and (model_id is None or ref.model_id == model_id):
            out.append(f)
    return out


def _refuse_in_use(provider: str, model_id: Optional[str] = None) -> None:
    refs = references(provider, model_id)
    if refs:
        what = f"«{provider}::{model_id}»" if model_id else f"«{provider}»"
        raise ProviderError(409, "in_use", f"{what} is in use by: {', '.join(refs)}", extra={"refs": refs})


# ── Bedrock, the built-in provider ───────────────────────────────────────────

def bedrock_enabled() -> bool:
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    try:
        stored = runtime_settings.get(RUNTIME_KEY)
    except Exception:       # a database without the table (an old copy before init_db): the yaml default stands
        stored = None
    if isinstance(stored, dict) and isinstance(stored.get("bedrock_enabled"), bool):
        return stored["bedrock_enabled"]
    return bool(settings.model_providers.bedrock_enabled)


def bedrock_references() -> list[str]:
    """The model settings that resolve to a Bedrock model — what turning Bedrock off leaves without a model."""
    out = []
    for f in MODEL_SETTING_FIELDS:
        value = effective_value(f)
        if not value:
            continue
        try:
            if parse_ref(value).is_bedrock:
                out.append(f)
        except ValueError:
            continue
    return out


def set_bedrock_enabled(enabled: bool, actor) -> dict:
    from agenticops.models import get_db_session
    from agenticops.services import runtime_settings
    before = bedrock_enabled()
    with get_db_session() as s:
        stored = runtime_settings.get(RUNTIME_KEY)
        value = dict(stored) if isinstance(stored, dict) else {}
        value["bedrock_enabled"] = bool(enabled)
        runtime_settings.put(RUNTIME_KEY, value, getattr(actor, "key", None), session=s)
        _audit(s, "update", "bedrock", actor, before={"bedrock_enabled": before},
               after={"bedrock_enabled": bool(enabled)})
    return {"enabled": bool(enabled), "references": bedrock_references()}
