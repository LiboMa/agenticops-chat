"""MVP-2.9.0 N25 (the 2.8.0 spec's S8, R18): the four high-impact switches — the executor, auto-fix, L0 / L1
auto-approval, the executor's human-in-the-loop gate — are kept in the database (`runtime_settings`), not in the
process: switching the executor off survives a restart, only an administrator changes them, every change is one audit
row, and EVERY reader asks `services/exec_switches` — never the process's `settings` attribute."""
import ast
import pathlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: F401 — imported at collection (the auth middleware is added only when auth is on at import)

FIELDS = ("executor_enabled", "auto_fix_enabled", "executor_auto_approve_l0_l1", "executor_hitl_enabled")
URL = "/api/settings"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.services import exec_switches, runtime_settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/switches.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    for field in FIELDS:
        monkeypatch.setattr(settings, field, False)
    models_mod.init_db()
    runtime_settings.reset_cache()
    exec_switches.invalidate()

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, settings=settings, monkeypatch=monkeypatch,
                          switches=exec_switches, store=runtime_settings)
    runtime_settings.reset_cache()
    exec_switches.invalidate()


def _values(env):
    e = env.switches.effective()
    return tuple(getattr(e, f) for f in FIELDS)


def _audits():
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return [(a.entity_id, a.actor, a.old_values, a.new_values)
                for a in s.query(AuditLog).filter(AuditLog.entity_name == "settings").order_by(AuditLog.id)]


# ── what is in force ──────────────────────────────────────────────────────────────────────────────────────────

def test_with_nothing_stored_the_yaml_values_apply(env):
    assert _values(env) == (False, False, False, False)
    env.monkeypatch.setattr(env.settings, "auto_fix_enabled", True)
    assert _values(env) == (False, True, False, False)
    assert env.switches.overridden() == []


def test_a_stored_value_wins_and_survives_a_restart(env):
    env.monkeypatch.setattr(env.settings, "executor_enabled", True)           # the yaml says «on»
    env.switches.save({"executor_enabled": False}, "user:root@x")              # an administrator switched it off
    assert _values(env)[0] is False and env.switches.overridden() == ["executor_enabled"]
    env.store.reset_cache(); env.switches.invalidate()                          # a new process: nothing in memory
    assert _values(env)[0] is False
    assert env.settings.executor_enabled is True                                # the yaml value itself was never touched


def test_a_stored_value_that_is_no_switch_is_never_on(env):
    env.store.put(env.switches.KEY, {"executor_enabled": "yes", "auto_fix_enabled": True, "made_up": True}, "x")
    env.switches.invalidate()
    assert _values(env) == (False, True, False, False)                          # re-validated at every read
    # N27 (review): something IS stored for the executor, and it reads as off — whatever the file's default says
    # (tests/test_review_fixes_n27.py); a name that is no switch is dropped
    assert env.switches.overridden() == ["auto_fix_enabled", "executor_enabled"]


def test_when_the_store_cannot_be_read_automation_is_off(env):
    for field in FIELDS:
        env.monkeypatch.setattr(env.settings, field, True)

    def boom(_key):
        raise RuntimeError("database is locked")
    env.monkeypatch.setattr(env.store, "get_row", boom)
    env.switches.invalidate()
    # nobody can tell whether an administrator switched something off: nothing runs or approves by itself
    assert _values(env) == (False, False, False, True)


def test_a_database_without_the_table_holds_no_override(env, tmp_path):
    import agenticops.models as models_mod
    for field in FIELDS:
        env.monkeypatch.setattr(env.settings, field, True)
    env.monkeypatch.setattr(models_mod, "_engine", None)
    env.monkeypatch.setattr(env.settings, "database_url", f"sqlite:///{tmp_path}/empty.db")
    env.store.reset_cache(); env.switches.invalidate()
    assert _values(env) == (True, True, True, True)


def test_a_change_made_by_another_process_is_seen_within_the_ttl(env):
    clock = [1000.0]
    env.monkeypatch.setattr(env.switches, "_clock", lambda: clock[0])
    assert _values(env)[0] is False
    env.store.put(env.switches.KEY, {"executor_enabled": True}, "cli:someone")  # written past this process's memo
    assert _values(env)[0] is False                                              # still the remembered answer
    clock[0] += env.switches.TTL_SECONDS + 0.01
    assert _values(env)[0] is True
    env.switches.save({"executor_enabled": False}, "user:root@x")                # a change made HERE is seen at once
    assert _values(env)[0] is False


# ── changing them ─────────────────────────────────────────────────────────────────────────────────────────────

def test_only_an_administrator_changes_them(env):
    body = {"executor_enabled": True, "auto_rca_enabled": False}
    env.monkeypatch.setattr(env.settings, "auto_rca_enabled", True)
    assert env.client.patch(URL, json=body).status_code == 401
    assert env.client.patch(URL, json=body, headers=env.login("ops@x", permissions=["read", "write"])).status_code == 403
    viewer = env.client.patch(URL, json=body, headers=env.login("eyes@x", permissions=["read"]))
    assert viewer.status_code == 403
    assert _values(env) == (False, False, False, False) and env.settings.auto_rca_enabled is True     # nothing applied
    assert env.switches.overridden() == [] and _audits() == []


def test_an_administrators_change_is_stored_and_audited(env):
    admin = env.login("root@x", is_admin=True)
    r = env.client.patch(URL, json={"executor_enabled": True, "executor_auto_approve_l0_l1": True, "auto_fix_enabled": False}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["executor_enabled"], body["auto_fix_enabled"], body["executor_auto_approve_l0_l1"], body["executor_hitl_enabled"]) == (True, False, True, False)
    info = body["execution_switches"]
    assert info["overridden"] == ["executor_auto_approve_l0_l1", "executor_enabled"]     # auto_fix did not change: not stored
    assert info["defaults"] == dict.fromkeys(FIELDS, False) and info["updated_by"] == "user:root@x" and info["updated_at"]
    assert _audits() == [("executor_auto_approve_l0_l1", "user:root@x", {"executor_auto_approve_l0_l1": False}, {"executor_auto_approve_l0_l1": True}),
                         ("executor_enabled", "user:root@x", {"executor_enabled": False}, {"executor_enabled": True})]
    assert env.settings.executor_enabled is False                               # the process's own attribute is not the store
    again = env.client.patch(URL, json={"executor_enabled": True}, headers=admin)
    assert again.status_code == 200 and len(_audits()) == 2                     # nothing changed: nothing written
    assert env.client.get(URL, headers=admin).json()["executor_enabled"] is True


def test_a_refused_body_applies_nothing(env):
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "auto_rca_enabled", True)
    r = env.client.patch(URL, json={"auto_rca_enabled": False, "executor_enabled": "yes"}, headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "executor_enabled must be a boolean"
    assert env.settings.auto_rca_enabled is True and _values(env)[0] is False and _audits() == []


def test_with_sign_in_off_the_change_is_still_audited(env):
    env.monkeypatch.setattr(env.settings, "api_auth_enabled", False)
    r = TestClient(agenticops.web.app.app).patch(URL, json={"executor_hitl_enabled": True})
    assert r.status_code == 200 and r.json()["executor_hitl_enabled"] is True
    assert [(a[0], a[3]) for a in _audits()] == [("executor_hitl_enabled", {"executor_hitl_enabled": True})]


def test_switching_the_executor_on_starts_its_queue_and_off_does_not(env):
    from unittest.mock import patch
    from agenticops.web import app as app_mod
    admin = env.login("root@x", is_admin=True)
    with patch.object(app_mod._executor_service, "start") as start:
        assert env.client.patch(URL, json={"executor_enabled": True}, headers=admin).status_code == 200
        start.assert_called_once()
        assert env.client.patch(URL, json={"executor_enabled": False}, headers=admin).status_code == 200
        start.assert_called_once()


# ── every reader follows what is in force ─────────────────────────────────────────────────────────────────────

def test_readers_follow_the_stored_value_not_the_process(env):
    from agenticops.agents.executor_agent import _build_executor_prompt, executor_agent
    from agenticops.services import ui_actions
    for field in FIELDS:
        env.monkeypatch.setattr(env.settings, field, True)                      # the yaml: everything on
    assert ui_actions.fix_approve_effect() == "approve_and_queue_execution"
    env.switches.save({"executor_enabled": False}, "user:root@x")
    admin = env.login("root@x", is_admin=True)
    assert ui_actions.fix_approve_effect() == "approve_only"
    assert "The executor is DISABLED" in _build_executor_prompt()
    assert executor_agent(fix_plan_id=1).startswith("Executor is DISABLED")
    assert env.client.get("/api/executor/status", headers=admin).json()["enabled"] is False
    execution = env.client.get("/api/setup/readiness", headers=admin).json()["execution"]
    assert (execution["executor_enabled"], execution["auto_fix_enabled"], execution["state"]) == (False, True, "partly_automatic")
    env.switches.save({"auto_fix_enabled": False}, "user:root@x")
    assert env.client.get("/api/setup/readiness", headers=admin).json()["execution"]["state"] == "manual"


def test_the_run_route_refuses_while_the_executor_is_switched_off(env):
    """«Run» on an approved plan asks the switch in force, whatever the process's own value says."""
    from agenticops.models import FixExecution, FixPlan, HealthIssue, RCAResult, get_db_session
    with get_db_session() as s:
        issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_approved", resource_id="r")
        s.add(issue)
        s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca)
        s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s", status="approved")
        s.add(plan)
        s.flush()
        plan_id = plan.id
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "executor_enabled", True)             # the yaml: on
    env.switches.save({"executor_enabled": False}, "user:root@x")              # an administrator: off
    refused = env.client.post(f"/api/fix-plans/{plan_id}/execute", json={}, headers=admin)
    assert refused.status_code == 403 and "Executor is disabled" in refused.json()["detail"]
    with get_db_session() as s:
        assert s.get(FixPlan, plan_id).status == "approved" and s.query(FixExecution).count() == 0
    env.monkeypatch.setattr(env.settings, "executor_enabled", False)            # the yaml: off
    env.switches.save({"executor_enabled": True}, "user:root@x")               # an administrator: on
    assert env.client.post(f"/api/fix-plans/{plan_id}/execute", json={}, headers=admin).status_code == 202
    with get_db_session() as s:
        assert s.get(FixPlan, plan_id).status == "executing" and s.query(FixExecution).count() == 1


def test_the_executors_human_gate_follows_the_stored_value(env):
    from agenticops.config import get_executor_interventions
    assert get_executor_interventions() == []
    env.switches.save({"executor_hitl_enabled": True}, "user:root@x")
    assert len(get_executor_interventions()) == 1                               # from the next executor build on


def test_the_pipeline_does_not_approve_by_itself_once_switched_off(env):
    from agenticops.services import pipeline_service
    env.monkeypatch.setattr(env.settings, "auto_fix_enabled", True)
    env.monkeypatch.setattr(env.settings, "executor_auto_approve_l0_l1", True)
    env.switches.save({"executor_auto_approve_l0_l1": False}, "user:root@x")
    called = []

    def looked():
        called.append("plan")
        raise RuntimeError("looked at a plan")
    # trigger_auto_approve imports get_db_session when it runs: this stands in for «it went on to read the plan»
    env.monkeypatch.setattr("agenticops.models.get_db_session", looked)
    pipeline_service.trigger_auto_approve(1, "TRC-test")                        # returns before it reads any plan
    assert called == []
    env.switches.save({"executor_auto_approve_l0_l1": True}, "user:root@x")     # … and with it on, it does go on
    pipeline_service.trigger_auto_approve(1, "TRC-test")
    assert called == ["plan"]


# ── nobody reads the process's attribute ──────────────────────────────────────────────────────────────────────

def _code_reads(path: pathlib.Path) -> list[str]:
    """Where CODE reaches one of the four switches on the settings object — `settings.<switch>`, the same through a
    name the object was imported under (`from agenticops.config import settings as _s`), through the module
    (`config.settings.<switch>`), or by `getattr(<it>, "<switch>")`. Comments and string literals are not code; an
    f-string's expressions are. Read from the syntax tree, which is the same on every supported Python — a token
    scan was not: before 3.12 an f-string is one string token (N27, review)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {"settings"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("config"):
            names |= {alias.asname or alias.name for alias in node.names if alias.name == "settings"}

    def is_settings(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in names) or (isinstance(node, ast.Attribute) and node.attr == "settings")

    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FIELDS and is_settings(node.value):
            hits.add(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2
              and is_settings(node.args[0]) and isinstance(node.args[1], ast.Constant) and node.args[1].value in FIELDS):
            hits.add(node.lineno)
    return [f"{path}:{line}" for line in sorted(hits)]


def test_no_code_reads_the_four_switches_past_the_one_reader():
    src = pathlib.Path(__file__).resolve().parent.parent / "src" / "agenticops"
    allowed = src / "services" / "exec_switches.py"
    hits = [hit for path in sorted(src.rglob("*.py")) if path != allowed for hit in _code_reads(path)]
    assert hits == []


def test_the_scan_sees_a_read_inside_an_f_string(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('x = f"The executor is {settings.executor_enabled}"\n# settings.auto_fix_enabled in a comment\ny = "settings.executor_hitl_enabled"\n', encoding="utf-8")
    assert _code_reads(sample) == [f"{sample}:1"]


def test_the_scan_follows_the_names_the_settings_object_goes_by(tmp_path):
    """N27 (review): `_s.executor_enabled` after `from agenticops.config import settings as _s` passed the scan —
    and so did `getattr(settings, "auto_fix_enabled")` and `config.settings.executor_enabled`."""
    sample = tmp_path / "aliases.py"
    sample.write_text(
        "from agenticops.config import settings as _s\n"
        "from agenticops import config\n"
        "import agenticops.config as cfg\n"
        "a = _s.executor_enabled\n"
        "b = config.settings.auto_fix_enabled\n"
        "c = cfg.settings.executor_hitl_enabled\n"
        "d = getattr(_s, 'executor_auto_approve_l0_l1')\n"
        "e = getattr(config.settings, \"executor_enabled\", False)\n"
        "f = _s.scan_focus\n"                                    # another setting: not a switch
        "g = switches.executor_enabled\n"                        # the value in force, from the one reader
        "h = other.executor_enabled\n",                          # not the settings object
        encoding="utf-8")
    assert _code_reads(sample) == [f"{sample}:{line}" for line in (4, 5, 6, 7, 8)]


def test_the_scan_does_not_depend_on_how_this_python_splits_an_f_string():
    """The scan used `tokenize`, which hands an f-string over as ONE string token before Python 3.12 — the read
    inside it was invisible there and the test above failed on 3.11, the oldest version this project supports.
    It reads the syntax tree now, where an f-string's expressions are nodes on every version."""
    import inspect
    assert "tokenize" not in inspect.getsource(_code_reads) and "ast." in inspect.getsource(_code_reads)


# ── every other change of PATCH /api/settings leaves an audit row too (S8: «还没有的就补上») ────────────────────────

@pytest.fixture
def no_yaml(monkeypatch):
    """The handler persists some keys to settings.yaml: never the real file from a test."""
    written = []
    monkeypatch.setattr("agenticops.config.save_to_yaml", lambda updates: written.append(dict(updates)))
    return written


def _rows():
    return [(key, old, new) for key, _actor, old, new in _audits()]


def test_a_low_impact_change_is_audited_and_an_unchanged_value_is_not(env, no_yaml):
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "auto_rca_enabled", True)
    env.monkeypatch.setattr(env.settings, "notifications_enabled", True)
    r = env.client.patch(URL, json={"auto_rca_enabled": False, "notifications_enabled": True}, headers=admin)
    assert r.status_code == 200
    assert _rows() == [("auto_rca_enabled", {"auto_rca_enabled": True}, {"auto_rca_enabled": False})]
    assert _audits()[0][1] == "user:root@x"


def test_scan_focus_models_and_the_report_store_are_audited(env, no_yaml):
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "scan_focus", "all")
    env.monkeypatch.setattr(env.settings, "agent_rca_model_id", "global.anthropic.claude-opus-5-5")
    env.monkeypatch.setattr(env.settings, "report_s3_prefix", "reports/")
    r = env.client.patch(URL, json={"scan_focus": "computing,security",
                                    "agent_models": {"rca": {"model_id": "global.anthropic.claude-sonnet-5-5"}},
                                    "report_s3_prefix": "ops/"}, headers=admin)
    assert r.status_code == 200, r.text
    assert sorted(_rows()) == [
        ("agent_rca_model_id", {"agent_rca_model_id": "global.anthropic.claude-opus-5-5"}, {"agent_rca_model_id": "global.anthropic.claude-sonnet-5-5"}),
        ("report_s3_prefix", {"report_s3_prefix": "reports/"}, {"report_s3_prefix": "ops/"}),
        ("scan_focus", {"scan_focus": "all"}, {"scan_focus": "computing,security"})]


def test_what_was_applied_before_a_refusal_is_still_audited(env, no_yaml):
    """The low-impact keys are applied one by one: a later key that is refused does not undo an earlier one."""
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "auto_rca_enabled", True)
    r = env.client.patch(URL, json={"auto_rca_enabled": False, "agent_models": {"nobody": {"model_id": "x"}}}, headers=admin)
    assert r.status_code == 400 and env.settings.auto_rca_enabled is False
    assert _rows() == [("auto_rca_enabled", {"auto_rca_enabled": True}, {"auto_rca_enabled": False})]


def test_a_high_impact_switch_is_audited_once(env, no_yaml):
    admin = env.login("root@x", is_admin=True)
    env.monkeypatch.setattr(env.settings, "auto_rca_enabled", True)
    assert env.client.patch(URL, json={"executor_enabled": True, "auto_rca_enabled": False}, headers=admin).status_code == 200
    assert sorted(key for key, _o, _n in _rows()) == ["auto_rca_enabled", "executor_enabled"]


# ── the store itself ──────────────────────────────────────────────────────────────────────────────────────────

def test_one_change_does_not_drop_another(env):
    env.switches.save({"executor_enabled": True}, "user:root@x")
    env.switches.save({"executor_hitl_enabled": True}, "user:root@x")
    assert env.switches.overridden() == ["executor_enabled", "executor_hitl_enabled"]
    assert _values(env) == (True, False, False, True)


def test_what_is_remembered_belongs_to_one_database(env, tmp_path):
    """Within the second a value is remembered, another database must not be answered from it."""
    import agenticops.models as models_mod
    env.switches.save({"executor_enabled": True}, "user:root@x")
    assert _values(env)[0] is True
    env.monkeypatch.setattr(models_mod, "_engine", None)
    env.monkeypatch.setattr(env.settings, "database_url", f"sqlite:///{tmp_path}/other.db")
    models_mod.init_db()                                                        # no invalidate(): the memo is still warm
    assert _values(env)[0] is False


@pytest.mark.parametrize("patch,field", [({"made_up": True}, "made_up"), ({"executor_enabled": "yes"}, "executor_enabled"),
                                         ({"auto_fix_enabled": 1}, "auto_fix_enabled")])
def test_only_a_switch_with_a_boolean_is_stored(env, patch, field):
    with pytest.raises(env.switches.ExecSwitchError) as refused:
        env.switches.save(patch, "user:root@x")
    assert refused.value.field == field and env.switches.overridden() == []
