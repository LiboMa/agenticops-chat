"""Model providers beyond Bedrock (MVP-2.9.0 N35, owner 2026-11-25): model references, presets, the provider registry.

A model is referenced as `<provider>::<model id>`; a value without `::` is a Bedrock model id, so every existing setting
keeps its meaning. Providers live in the database (admin-managed, the API key encrypted with the credential store,
never shown, every write audited); Bedrock is the built-in one and can be turned off.
"""
import json
from types import SimpleNamespace

import pytest

from tests.test_viewer_role import _temp_db

ADMIN = SimpleNamespace(key="user:root", user_id=1)


@pytest.fixture
def db(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "n35.db")
    from agenticops.credentials.store import reset_credential_store
    from agenticops.llm import registry
    from agenticops.services import runtime_settings
    monkeypatch.delenv("AIOPS_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("AIOPS_MASTER_KEY", "n35-test-master-key-0123456789abcdef")
    reset_credential_store()
    runtime_settings.reset_cache()
    registry.reset_cache()
    for name in [f"agent_{a}_model_id" for a in ("main", "scan", "detect", "rca", "sre", "executor", "reporter")]:
        monkeypatch.setattr(settings, name, "global.anthropic.claude-opus-5-5")
    yield settings
    reset_credential_store()
    runtime_settings.reset_cache()
    registry.reset_cache()


def _make(name="ollama-local", **over):
    from agenticops.llm import registry
    data = {"name": name, "display_name": "Ollama", "preset": "ollama", "kind": "openai_compatible",
            "base_url": "http://localhost:11434/v1", "api_key": "sk-test-SECRET-123456"}
    data.update(over)
    return registry.create(data, ADMIN)


# ── references ───────────────────────────────────────────────────────────────

def test_parse_ref():
    from agenticops.llm.refs import ModelRef, format_ref, parse_ref
    assert parse_ref("global.anthropic.claude-opus-5-5").is_bedrock
    assert parse_ref("global.anthropic.claude-opus-5-5") == ModelRef(None, "global.anthropic.claude-opus-5-5")
    assert parse_ref("arn:aws:bedrock:us-east-1:123456789012:inference-profile/x").is_bedrock
    assert parse_ref("ollama-local::qwen3:32b") == ModelRef("ollama-local", "qwen3:32b")
    assert parse_ref("openrouter::anthropic/claude-sonnet-4.5").model_id == "anthropic/claude-sonnet-4.5"
    assert parse_ref("p1::a::b") == ModelRef("p1", "a::b")
    for bad in ("::x", "P!::x", "p1::", "bedrock::x", ""):
        with pytest.raises(ValueError):
            parse_ref(bad)
    assert format_ref("ollama-local", "qwen3:32b") == "ollama-local::qwen3:32b"


def test_presets_cover_the_named_platforms():
    from agenticops.llm.presets import PRESETS
    assert set(PRESETS) == {"litellm_proxy", "openrouter", "vllm", "ollama", "lmstudio", "sub2api", "anthropic",
                            "custom_openai", "custom_anthropic"}
    assert PRESETS["ollama"].base_url == "http://localhost:11434/v1" and not PRESETS["ollama"].needs_key
    assert PRESETS["openrouter"].base_url == "https://openrouter.ai/api/v1" and PRESETS["openrouter"].needs_key
    assert PRESETS["litellm_proxy"].base_url == "http://localhost:4000/v1"
    assert PRESETS["vllm"].base_url == "http://localhost:8000/v1"
    assert PRESETS["lmstudio"].base_url == "http://localhost:1234/v1"
    assert PRESETS["sub2api"].kind == "anthropic_compatible" and PRESETS["sub2api"].base_url == ""
    assert PRESETS["anthropic"].kind == "anthropic_compatible"
    assert PRESETS["custom_openai"].kind == "openai_compatible" and PRESETS["custom_anthropic"].kind == "anthropic_compatible"


# ── the registry ─────────────────────────────────────────────────────────────

def test_create_stores_the_key_encrypted_and_never_lists_it(db):
    from agenticops.llm import registry
    from agenticops.llm.models import ModelProvider
    from agenticops.models import get_session
    _make()
    s = get_session()
    row = s.query(ModelProvider).filter_by(name="ollama-local").one()
    assert "sk-test-SECRET-123456" not in json.dumps(row.secrets)
    s.close()
    listed = registry.list_public()
    assert "sk-test-SECRET-123456" not in json.dumps(listed) and listed[0]["has_api_key"] is True
    assert registry.get("ollama-local").api_key == "sk-test-SECRET-123456"



def test_header_values_are_stored_with_the_key(db):
    from agenticops.llm import registry
    from agenticops.llm.models import ModelProvider
    from agenticops.models import get_session
    _make(extra_headers={"HTTP-Referer": "https://ops.example.com", "X-Title": "header-SECRET-777"})
    s = get_session()
    stored = json.dumps(s.query(ModelProvider).filter_by(name="ollama-local").one().secrets)
    s.close()
    assert "header-SECRET-777" not in stored and "ops.example.com" not in stored
    assert registry.get("ollama-local").extra_headers["X-Title"] == "header-SECRET-777"
    assert registry.list_public()[0]["header_names"] == ["HTTP-Referer", "X-Title"]
    registry.update("ollama-local", {"extra_headers": {"HTTP-Referer": "****", "X-Title": "new-title"}}, ADMIN)
    cfg = registry.get("ollama-local")
    assert cfg.extra_headers == {"HTTP-Referer": "https://ops.example.com", "X-Title": "new-title"}

def test_plaintext_backend_still_keeps_the_key_intact(db, monkeypatch):
    from agenticops.credentials.store import get_credential_store, reset_credential_store
    from agenticops.llm import registry
    monkeypatch.delenv("AIOPS_MASTER_KEY", raising=False)
    reset_credential_store()
    assert get_credential_store().backend_name == "plaintext"
    _make()
    registry.reset_cache()
    assert registry.get("ollama-local").api_key == "sk-test-SECRET-123456"     # not scrubbed to [REDACTED-SECRET]


def test_update_merges_like_accounts(db):
    from agenticops.llm import registry
    _make()
    for keep in ("", "****3456", None):
        body = {"base_url": "http://gpu-box:11434/v1"} if keep is None else {"api_key": keep}
        registry.update("ollama-local", body, ADMIN)
        assert registry.get("ollama-local").api_key == "sk-test-SECRET-123456"
    assert registry.get("ollama-local").base_url == "http://gpu-box:11434/v1"
    registry.update("ollama-local", {"api_key": "sk-new-999"}, ADMIN)
    assert registry.get("ollama-local").api_key == "sk-new-999"
    registry.update("ollama-local", {}, ADMIN, clear_api_key=True)
    assert registry.get("ollama-local").api_key == ""
    with pytest.raises(registry.ProviderError) as e:
        registry.update("ollama-local", {"name": "renamed"}, ADMIN)
    assert e.value.code == "invalid_name"


def test_names(db):
    from agenticops.llm import registry
    for name, code in (("bedrock", "reserved_name"), ("Bad Name", "invalid_name"), ("x", "invalid_name")):
        with pytest.raises(registry.ProviderError) as e:
            _make(name=name)
        assert e.value.code == code
    _make()
    with pytest.raises(registry.ProviderError) as e:
        _make()
    assert e.value.code == "name_taken"


def test_base_url(db):
    from agenticops.llm import registry
    _make(base_url="http://h:4000/")
    assert registry.get("ollama-local").base_url == "http://h:4000"
    for bad in ("ftp://x", "localhost:4000", "", "http://"):
        with pytest.raises(registry.ProviderError) as e:
            _make(name="other-one", base_url=bad)
        assert e.value.code == "invalid_base_url"
    with pytest.raises(registry.ProviderError) as e:
        _make(name="other-two", kind="grpc")
    assert e.value.code == "invalid_kind"


def test_delete_and_disable_refuse_while_a_setting_uses_it(db):
    from agenticops.llm import registry
    _make()
    db.agent_main_model_id = "ollama-local::qwen3:32b"
    assert registry.references("ollama-local") == ["agent_main_model_id"]
    assert registry.references("ollama-local", "qwen3:32b") == ["agent_main_model_id"]
    assert registry.references("ollama-local", "other") == []
    for act in (lambda: registry.delete("ollama-local", ADMIN), lambda: registry.set_enabled("ollama-local", False, ADMIN)):
        with pytest.raises(registry.ProviderError) as e:
            act()
        assert e.value.code == "in_use" and e.value.extra == {"refs": ["agent_main_model_id"]}
    db.agent_main_model_id = "global.anthropic.claude-opus-5-5"
    registry.delete("ollama-local", ADMIN)
    assert registry.get("ollama-local") is None


def test_every_write_is_audited_without_the_key(db):
    from agenticops.audit.models import AuditLog
    from agenticops.llm import registry
    from agenticops.models import get_session
    _make()
    registry.update("ollama-local", {"api_key": "sk-new-999"}, ADMIN)
    registry.update("ollama-local", {"timeout_seconds": 90}, ADMIN)
    registry.update("ollama-local", {}, ADMIN, clear_api_key=True)
    registry.set_enabled("ollama-local", False, ADMIN)
    registry.delete("ollama-local", ADMIN)
    registry.set_bedrock_enabled(False, ADMIN)
    s = get_session()
    rows = s.query(AuditLog).filter(AuditLog.entity_type == "model_provider").order_by(AuditLog.id).all()
    s.close()
    text = json.dumps([[r.action, r.old_values, r.new_values, r.details] for r in rows], default=str)
    assert "sk-test-SECRET-123456" not in text and "sk-new-999" not in text
    assert [r.details.get("key_change") for r in rows[:4]] == ["added", "replaced", "kept", "removed"]
    assert len(rows) == 7


def test_bedrock_switch(db):
    from agenticops.llm import registry
    assert registry.bedrock_enabled() is True                         # the settings.yaml default
    db.agent_scan_model_id = ""                                        # falls back to the cheap tier — a Bedrock id
    refs = registry.bedrock_references()
    assert "agent_main_model_id" in refs and "agent_scan_model_id" in refs
    registry.set_bedrock_enabled(False, ADMIN)
    assert registry.bedrock_enabled() is False
    registry.set_bedrock_enabled(True, ADMIN)
    assert registry.bedrock_enabled() is True


def test_every_preset_has_its_words_in_both_languages():
    """The platform cards are the server's presets; their words are the page's (N35 E2E: the Chinese page showed the
    English notes) — every preset has notes in en and zh, and the two «Other» ones a label."""
    import json
    import pathlib
    from agenticops.llm.presets import PRESETS
    root = pathlib.Path(__file__).resolve().parents[1] / "src/agenticops/web/frontend/src/locales"
    for lang in ("en", "zh"):
        words = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
        for key in PRESETS:
            assert words.get(f"settings.providers.preset.{key}.notes"), (lang, key)
        for key in ("custom_openai", "custom_anthropic"):
            assert words.get(f"settings.providers.preset.{key}.label"), (lang, key)
