"""The approved plan reaches the agent that acts on it whole (MVP-2.9.0 N28).

Found in the real run inside the lab cluster, 2026-11-20. Every agent build carries the context offloader: a tool
result longer than 6,000 characters is replaced by its first 3,000 and a reference. `get_approved_fix_plan` — what
the executor will run and verify — is such a result more often than not (63 of the 86 plans that were approved or
run on the copy database), and it is ONE line of JSON, so the offloader's own search can hand back at most its first
6,000 characters: the rollback, which comes last, is what goes missing. The executor fetched the rest by itself that
time. The plan it acts on must not depend on that.

These tests run a real `strands.Agent` with the plugin `get_agent_context_plugins` builds — no Bedrock: a scripted
model that keeps what each model call was sent.
"""
import json

import pytest
from strands import Agent, tool

from agenticops.config import get_agent_context_plugins, settings
from tests.test_run_stop_told import Recording, _texts

PLAN = json.dumps({
    "id": 7, "label": "I#12 fix plan v1",
    "steps": [{"action": f"restore workload {i}", "command": f"kubectl scale deployment/app-{i} --replicas=2 -n shop"}
              for i in range(120)],
    "post_checks": [{"check_id": "pc-1", "command": "kubectl get deploy -n shop"}],
    "rollback_plan": {"steps": [{"action": "keep the last one at its baseline",
                                 "command": "kubectl scale deployment/app-119 --replicas=2 -n shop"}]},
    "approved_hash": "END-OF-THE-PLAN",
})
LISTING = "\n".join(f"resource-{i:05d} us-east-1 running" for i in range(600))


def _agent(model):
    @tool
    def get_approved_fix_plan(fix_plan_id: int) -> str:
        """The approved plan."""
        return PLAN

    @tool
    def get_managed_resources(region: str = "") -> str:
        """A long listing."""
        return LISTING

    return Agent(model=model, tools=[get_approved_fix_plan, get_managed_resources], callback_handler=None,
                 plugins=get_agent_context_plugins("executor"))


@pytest.fixture(autouse=True)
def _offloader_on(monkeypatch):
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)


def test_the_two_results_are_both_far_over_the_offload_limit():
    limit = settings.context_offload_max_result_tokens * 4          # the SDK's estimate: four characters a token
    assert len(PLAN) > 2 * limit and len(LISTING) > 2 * limit
    assert "\n" not in PLAN                                          # one line, as the tool writes it


def test_the_approved_plan_reaches_the_model_whole():
    model = Recording([[("get_approved_fix_plan", {"fix_plan_id": 7})], "read it"])
    _agent(model)("go")
    seen = _texts(model.sent[1])                                     # what the model was sent after the tool ran
    assert PLAN in seen                                              # the very text, to its last character
    assert not any(t.lstrip().startswith("[Offloaded:") for t in seen)


def test_another_tools_long_result_is_still_a_preview():
    model = Recording([[("get_managed_resources", {})], "read it"])
    _agent(model)("go")
    seen = _texts(model.sent[1])
    assert LISTING not in seen
    preview = next(t for t in seen if t.lstrip().startswith("[Offloaded:"))
    assert "resource-00000" in preview and "resource-00599" not in preview


def test_in_one_turn_the_plan_is_whole_and_the_listing_is_not():
    model = Recording([[("get_managed_resources", {}), ("get_approved_fix_plan", {"fix_plan_id": 7})], "read both"])
    _agent(model)("go")
    seen = _texts(model.sent[1])
    assert PLAN in seen and LISTING not in seen
    assert sum(t.lstrip().startswith("[Offloaded:") for t in seen) == 1


def test_the_plan_stays_whole_in_the_later_calls_of_the_run():
    model = Recording([[("get_approved_fix_plan", {"fix_plan_id": 7})], [("get_managed_resources", {})], "done"])
    _agent(model)("go")
    assert PLAN in _texts(model.sent[2])                             # still the whole plan two model calls later
