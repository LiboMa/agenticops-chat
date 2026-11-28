"""A provider's protocol is named in ONE place (review of MVP-2.9.0, ①): `llm/presets` (`OPENAI`, `ANTHROPIC`,
`KINDS`, `default_preset`); the registry refuses an unknown one with one check, whichever write carries it."""
import pathlib

import pytest

from tests.llm_fake_server import ADMIN, add_provider, llm_db

LLM = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops" / "llm"


@pytest.fixture
def db(tmp_path, monkeypatch):
    return llm_db(tmp_path, monkeypatch, "llm-kinds.db")


def test_default_preset():
    from agenticops.llm.presets import ANTHROPIC, OPENAI, PRESETS, default_preset
    assert default_preset(ANTHROPIC) == "custom_anthropic" and default_preset(OPENAI) == "custom_openai"
    assert default_preset(None) == "custom_openai" and default_preset("grpc") == "custom_openai"
    assert {PRESETS[default_preset(k)].kind for k in (ANTHROPIC, OPENAI)} == {ANTHROPIC, OPENAI}


def test_every_write_refuses_an_unknown_protocol_alike(db):
    from agenticops.llm import registry
    add_provider("pp-old", "http://h/v1")
    calls = [lambda: registry.create({"name": "qq-new", "kind": "grpc", "preset": "custom_openai",
                                      "base_url": "http://h/v1"}, ADMIN),
             lambda: registry.update("pp-old", {"kind": "grpc"}, ADMIN),
             lambda: registry.draft_config({"name": "qq-new", "kind": "grpc", "preset": "custom_openai",
                                            "base_url": "http://h/v1"}),
             lambda: registry.draft_config({"kind": "grpc"}, existing="pp-old")]
    seen = set()
    for call in calls:
        with pytest.raises(registry.ProviderError) as e:
            call()
        seen.add((e.value.status, e.value.code, str(e.value)))
    assert len(seen) == 1 and next(iter(seen))[:2] == (422, "invalid_kind")


def test_no_module_spells_a_protocol_out():
    for path in LLM.glob("*.py"):
        if path.name == "presets.py":
            continue
        src = path.read_text()
        assert '"anthropic_compatible"' not in src and '"openai_compatible"' not in src, path.name
