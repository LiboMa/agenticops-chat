# tests/test_policy_engine_change.py
from datetime import datetime, timedelta, timezone

from agenticops.services.policy_engine import PolicyEngine, validate_policy


def _engine(rules, freeze=None):
    return PolicyEngine({"version": 1, "defaults": {"action": "require_human"},
                         "freeze_windows": freeze or [], "rules": rules})


def test_plan_kind_match_isolates_change_rules():
    eng = _engine([
        {"name": "change-tags-auto", "match": {"plan_kind": ["change"], "action_type": ["tag"], "risk_level": ["L0", "L1"]},
         "action": "auto_approve", "itsm_change_type": "standard"},
        {"name": "fix-low-auto", "match": {"plan_kind": ["fix"], "risk_level": ["L0", "L1"]}, "action": "auto_approve"},
    ])
    d = eng.evaluate(risk_level="L1", plan_kind="change", action_type="tag")
    assert d.action == "auto_approve" and d.rule_name == "change-tags-auto" and d.itsm_change_type == "standard"
    d2 = eng.evaluate(risk_level="L1", plan_kind="change", action_type="network")
    assert d2.action == "require_human" and d2.rule_name == "(default)"
    d3 = eng.evaluate(risk_level="L1")  # fix, default plan_kind
    assert d3.rule_name == "fix-low-auto"


def test_emergency_bypasses_freeze_window():
    now = datetime.now(timezone.utc)
    freeze = [{"name": "cny", "start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=1)).isoformat()}]
    eng = _engine([
        {"name": "freeze-window-block", "match": {"in_change_freeze": True}, "action": "block"},
        {"name": "human", "match": {}, "action": "require_human"},
    ], freeze)
    assert eng.evaluate(risk_level="L1", plan_kind="change").action == "block"
    d = eng.evaluate(risk_level="L1", plan_kind="change", emergency=True)
    assert d.action == "require_human" and d.rule_name == "human"


def test_emergency_does_not_lift_freeze_for_fix_plans():
    # `emergency` is a change-plan concept: on the fix flow (plan_kind defaults to "fix") a freeze still blocks.
    now = datetime.now(timezone.utc)
    freeze = [{"name": "cny", "start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=1)).isoformat()}]
    eng = _engine([
        {"name": "freeze-window-block", "match": {"in_change_freeze": True}, "action": "block"},
        {"name": "human", "match": {}, "action": "require_human"},
    ], freeze)
    d = eng.evaluate(risk_level="L1", emergency=True)
    assert d.action == "block" and d.rule_name == "freeze-window-block"


def test_emergency_match_field():
    eng = _engine([{"name": "emergency-human", "match": {"emergency": True}, "action": "require_human", "itsm_change_type": "emergency"},
                   {"name": "rest", "match": {}, "action": "auto_approve"}])
    assert eng.evaluate(risk_level="L1", emergency=True).itsm_change_type == "emergency"
    assert eng.evaluate(risk_level="L1", emergency=False).rule_name == "rest"


def test_legacy_rules_unchanged_for_fix():
    from agenticops.services.policy_engine import DEFAULT_POLICY
    eng = PolicyEngine(DEFAULT_POLICY)
    assert eng.evaluate(risk_level="L1").action == "auto_approve"
    assert eng.evaluate(risk_level="L2").action == "require_human"


def test_validate_new_fields():
    bad = {"rules": [{"name": "x", "match": {"plan_kind": ["bogus"]}, "action": "block"},
                     {"name": "y", "match": {"action_type": "tag"}, "action": "block"},
                     {"name": "z", "match": {"emergency": "yes"}, "action": "block"}]}
    errors = validate_policy(bad)
    assert len(errors) == 3


def test_shipped_policy_file_valid_and_has_change_rules():
    from agenticops.services.policy_engine import get_policy_engine
    eng = get_policy_engine(reload=True)
    d = eng.evaluate(risk_level="L1", plan_kind="change", action_type="tag")
    assert d.action == "auto_approve" and d.itsm_change_type == "standard"
    assert eng.evaluate(risk_level="L3", plan_kind="change").action == "require_human"
    # An emergency change is never a standard change (ITIL): even a low-risk tag needs a human approver.
    # The effective type becomes "emergency" later in change_service, not here.
    e = eng.evaluate(risk_level="L1", plan_kind="change", action_type="tag", emergency=True)
    assert e.action == "require_human" and e.rule_name == "change-normal-human" and e.itsm_change_type == "normal"
