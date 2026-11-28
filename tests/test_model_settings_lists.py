"""One list of model settings, one fallback rule, one Galaxy write (review of MVP-2.9.0, ②).

The nine model settings beside the agents' own were named three times (the registry's report order, the API's
names, the fallbacks) and the Galaxy model could be written two ways with two checks: the top-level
`galaxy_model_id` had to be one of the listed models, `model_settings.galaxy` did not, and a request carrying both
wrote the yaml twice. Now `registry.MODEL_SETTINGS` is the one map, `registry.fallback` the one rule, and the Galaxy
value — whichever key carries it — is checked and written once, with the other model settings."""
from tests.test_settings_model_refs import URL, env  # noqa: F401  (the fixture)


def test_one_list():
    from agenticops.config import AGENT_NAMES
    from agenticops.llm import model_settings, registry
    assert model_settings.SETTINGS is registry.MODEL_SETTINGS
    assert registry.AGENT_MODEL_FIELDS == tuple(f"agent_{n}_model_id" for n in AGENT_NAMES)
    assert registry.MODEL_SETTING_FIELDS == registry.AGENT_MODEL_FIELDS + tuple(registry.MODEL_SETTINGS.values())
    assert set(registry.TIER_FIELDS) | set(registry.CHEAP_DEFAULT_FIELDS) | {"executor_simple_model_id"} == \
        set(registry.MODEL_SETTINGS.values())


def test_one_fallback_rule(env):
    from agenticops.config import get_agent_model_config
    from agenticops.llm import model_settings, registry
    s = env.settings
    assert not hasattr(model_settings, "fallback")                          # the registry's rule, nobody else's
    for field in registry.TIER_FIELDS:
        assert registry.fallback(field) is None
    assert registry.fallback("executor_simple_model_id") == get_agent_model_config("executor")[0]
    for field in registry.CHEAP_DEFAULT_FIELDS:
        assert registry.fallback(field) == s.bedrock_model_id_cheap
    env.monkeypatch.setattr(s, "agent_rca_model_id", "")
    assert registry.fallback("agent_rca_model_id") == get_agent_model_config("rca")[0]
    env.monkeypatch.setattr(s, "executor_simple_model_id", "")
    assert registry.effective_value("executor_simple_model_id") == ""       # counted under the executor's own setting
    assert model_settings.effective("executor_simple_model_id") == get_agent_model_config("executor")[0]


def test_the_galaxy_model_has_one_check_whichever_key_carries_it(env):
    h = env.login("root", is_admin=True)
    before = env.settings.galaxy_model_id
    for body in ({"galaxy_model_id": "global.anthropic.not-a-listed-model"},
                 {"model_settings": {"galaxy": "global.anthropic.not-a-listed-model"}}):
        r = env.client.patch(URL, headers=h, json=body)
        assert r.status_code == 400 and "galaxy" in r.text, (body, r.text)
    assert env.settings.galaxy_model_id == before and env.written == []


def test_a_galaxy_change_is_written_once_with_the_other_model_settings(env):
    h = env.login("root", is_admin=True)
    r = env.client.patch(URL, headers=h, json={"model_settings": {"security": "local-llm::fake-chat-1",
                                                                  "galaxy": ""},
                                               "galaxy_model_id": "local-llm::fake-chat-1"})
    assert r.status_code == 200, r.text
    assert env.written == [{"security_model_id": "local-llm::fake-chat-1", "galaxy_model_id": "local-llm::fake-chat-1"}]
    assert env.settings.galaxy_model_id == "local-llm::fake-chat-1"        # the top-level key wins, as before
