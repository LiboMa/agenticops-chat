"""MVP-2.9.0 N14: what a new fix plan changed relative to the plan before it on the same issue.

A plan that is sent back is redone as a NEW row (its version starts again at 1); the row that was sent back keeps
its content. So «what changed» needs nothing stored: it is this plan against the newest older plan of its issue,
step by step, by what would RUN — the command, or for a step without one the words it has.
"""
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services.change_steps import plan_diff, step_line

T0 = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


class TestStepLine:
    def test_a_step_is_compared_by_its_command(self):
        assert step_line({"action": "Restart the web tier", "command": "kubectl  rollout restart\n deploy/web"}) == "kubectl rollout restart deploy/web"

    def test_a_step_without_a_command_by_what_it_says(self):
        assert step_line({"action": "Ask the DBA to  confirm the replica lag"}) == "Ask the DBA to confirm the replica lag"
        assert step_line({"description": "Wait 5 minutes"}) == "Wait 5 minutes"
        assert step_line("Wait for the rollout") == "Wait for the rollout"

    def test_a_step_written_with_unknown_keys_as_it_is(self):
        assert step_line({"tool": "x", "args": [1]}) == '{"args": [1], "tool": "x"}'      # keys sorted: the same step is the same line
        assert step_line(None) == ""


class TestPlanDiff:
    A = [{"action": "scale up", "command": "kubectl scale deploy/web --replicas=4"},
         {"action": "restart", "command": "kubectl rollout restart deploy/web"},
         {"action": "watch", "command": "kubectl rollout status deploy/web"}]

    def test_the_same_steps_are_all_unchanged(self):
        assert plan_diff(self.A, [dict(s) for s in self.A]) == {"added": [], "removed": [], "modified": [], "unchanged": 3}

    def test_a_changed_command_is_modified_with_both_texts(self):
        b = [dict(s) for s in self.A]
        b[0]["command"] = "kubectl scale deploy/web --replicas=6"
        assert plan_diff(self.A, b) == {
            "added": [], "removed": [], "unchanged": 2,
            "modified": [{"previous_step": 1, "step": 1, "previous": "kubectl scale deploy/web --replicas=4",
                          "now": "kubectl scale deploy/web --replicas=6"}]}

    def test_an_added_and_a_removed_step_are_numbered_in_their_own_plan(self):
        b = [self.A[0], self.A[2], {"action": "note", "command": "kubectl annotate deploy/web fixed=true"}]
        d = plan_diff(self.A, b)
        assert d["removed"] == [{"previous_step": 2, "text": "kubectl rollout restart deploy/web"}]
        assert d["added"] == [{"step": 3, "text": "kubectl annotate deploy/web fixed=true"}]
        assert d["modified"] == [] and d["unchanged"] == 2

    def test_a_step_without_a_command_is_compared_by_its_words(self):
        """diff_steps (a request against its plan) compares commands only: two command-less steps were «the same»
        whatever they said."""
        d = plan_diff([{"action": "Ask the DBA before the failover"}], [{"action": "Tell the DBA after the failover"}])
        assert d["unchanged"] == 0 and d["modified"] == [{"previous_step": 1, "step": 1, "previous": "Ask the DBA before the failover",
                                                           "now": "Tell the DBA after the failover"}]

    def test_reworded_text_around_the_same_command_is_not_a_change_to_what_runs(self):
        d = plan_diff([{"action": "restart", "command": "systemctl restart nginx"}],
                      [{"action": "Restart nginx so it picks up the new config", "command": "systemctl restart nginx"}])
        assert d == {"added": [], "removed": [], "modified": [], "unchanged": 1}

    def test_nothing_against_something(self):
        assert plan_diff(None, self.A[:1]) == {"added": [{"step": 1, "text": "kubectl scale deploy/web --replicas=4"}],
                                               "removed": [], "modified": [], "unchanged": 0}
        assert plan_diff(self.A[:1], []) == {"added": [], "removed": [{"previous_step": 1, "text": "kubectl scale deploy/web --replicas=4"}],
                                             "modified": [], "unchanged": 0}
        assert plan_diff("not a list", None) == {"added": [], "removed": [], "modified": [], "unchanged": 0}


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/diff.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _issue(s):
    issue = HealthIssue(title="t", description="d", severity="high", source="test", status="fix_planned", resource_id="i-1")
    s.add(issue); s.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    s.add(rca); s.flush()
    return issue, rca


def _add(s, issue, rca, *, steps, status="pending_approval", rollback=None, risk="L2", at=T0, **kw):
    from agenticops.services.plan_content import stamp_content
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id if rca else None, risk_level=risk, title="p", summary="s",
                   status=status, steps=steps, rollback_plan=rollback, created_at=at, **kw)
    s.add(plan); s.flush()
    stamp_content(s, plan)
    return plan


STEPS_1 = [{"action": "restart everything", "command": "kubectl rollout restart deploy -n shop"},
           {"action": "watch", "command": "kubectl rollout status deploy/web -n shop"}]
STEPS_2 = [{"action": "restart only the web tier", "command": "kubectl rollout restart deploy/web -n shop"},
           {"action": "watch", "command": "kubectl rollout status deploy/web -n shop"},
           {"action": "check the endpoints", "command": "kubectl get endpoints web -n shop"}]


def test_the_first_plan_of_an_issue_has_nothing_before_it(client):
    s = get_session()
    issue, rca = _issue(s)
    pid = _add(s, issue, rca, steps=STEPS_1).id
    s.commit(); s.close()
    assert client.get(f"/api/fix-plans/{pid}/previous-diff").json() == {
        "plan_id": pid, "previous": None, "same_content": None, "steps": None, "rollback": None}


def test_a_redone_plan_says_what_it_changed_and_why_the_last_one_was_sent_back(client):
    s = get_session()
    issue, rca = _issue(s)
    old = _add(s, issue, rca, steps=STEPS_1, status="rejected", rollback={"steps": [{"command": "kubectl rollout undo deploy -n shop"}]},
               rejected_by="user:alice", rejected_at=T0 + timedelta(minutes=5), rejection_reason="restart only the web tier")
    new = _add(s, issue, rca, steps=STEPS_2, rollback={"steps": [{"command": "kubectl rollout undo deploy/web -n shop"}]},
               risk="L1", at=T0 + timedelta(minutes=9))
    old_id, new_id = old.id, new.id
    s.commit(); s.close()
    d = client.get(f"/api/fix-plans/{new_id}/previous-diff").json()
    assert d["plan_id"] == new_id and d["same_content"] is False
    p = d["previous"]
    assert (p["id"], p["status"], p["plan_version"], p["risk_level"]) == (old_id, "rejected", 1, "L2")
    assert (p["rejected_by"], p["rejection_reason"], p["rejection_is_feedback"], p["same_diagnosis"]) == \
        ("user:alice", "restart only the web tier", True, True)
    assert p["rejected_at"].startswith("2026-11-18T08:05") and p["rejected_at"].endswith("Z") and p["created_at"].endswith("Z")
    assert d["steps"] == {
        "modified": [{"previous_step": 1, "step": 1, "previous": "kubectl rollout restart deploy -n shop",
                      "now": "kubectl rollout restart deploy/web -n shop"}],
        "added": [{"step": 3, "text": "kubectl get endpoints web -n shop"}], "removed": [], "unchanged": 1}
    assert d["rollback"]["modified"] == [{"previous_step": 1, "step": 1, "previous": "kubectl rollout undo deploy -n shop",
                                          "now": "kubectl rollout undo deploy/web -n shop"}]


def test_a_plan_redone_word_for_word_says_so(client):
    s = get_session()
    issue, rca = _issue(s)
    _add(s, issue, rca, steps=STEPS_1, status="rejected", rejected_by="user:alice", rejection_reason="no")
    new_id = _add(s, issue, rca, steps=[dict(x) for x in STEPS_1], at=T0 + timedelta(minutes=9)).id
    s.commit(); s.close()
    d = client.get(f"/api/fix-plans/{new_id}/previous-diff").json()
    assert d["same_content"] is True
    assert d["steps"] == {"added": [], "removed": [], "modified": [], "unchanged": 2}


def test_a_rejection_made_by_code_is_not_a_persons_feedback(client):
    from agenticops.services.plan_content import CONTENT_CHANGED
    s = get_session()
    issue, rca = _issue(s)
    _add(s, issue, rca, steps=STEPS_1, status="rejected", rejected_by="user:alice", rejection_reason=CONTENT_CHANGED)
    new_id = _add(s, issue, rca, steps=STEPS_2, at=T0 + timedelta(minutes=9)).id
    s.commit(); s.close()
    p = client.get(f"/api/fix-plans/{new_id}/previous-diff").json()["previous"]
    assert p["rejection_is_feedback"] is False and p["rejection_reason"] == CONTENT_CHANGED


def test_the_plan_before_is_the_newest_older_plan_of_the_same_issue(client):
    s = get_session()
    issue, rca = _issue(s)
    other, other_rca = _issue(s)
    _add(s, issue, rca, steps=STEPS_1, status="rejected", rejected_by="user:alice", rejection_reason="first")
    failed = _add(s, issue, rca, steps=STEPS_2, status="failed", at=T0 + timedelta(minutes=10))
    _add(s, other, other_rca, steps=STEPS_1, status="rejected", rejected_by="user:bob", rejection_reason="another issue",
         at=T0 + timedelta(minutes=11))
    rca2 = RCAResult(health_issue_id=issue.id, root_cause="y", confidence=0.8)
    s.add(rca2); s.flush()
    new = _add(s, issue, rca2, steps=STEPS_1, at=T0 + timedelta(minutes=20))
    failed_id, new_id = failed.id, new.id
    s.commit(); s.close()
    p = client.get(f"/api/fix-plans/{new_id}/previous-diff").json()["previous"]
    assert (p["id"], p["status"], p["rejected_by"], p["rejection_reason"], p["rejection_is_feedback"]) == (failed_id, "failed", None, None, False)
    assert p["same_diagnosis"] is False                 # the new plan was written from a newer diagnosis


def test_a_change_plan_has_no_plan_before_it(client):
    s = get_session()
    cr = ChangeRequest(title="c", description="d", requested_by="user:bob", status="planned")
    s.add(cr); s.flush()
    for _ in range(2):
        s.add(FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s", status="pending_approval",
                      steps=STEPS_1))
    s.flush()
    pid = s.query(FixPlan).order_by(FixPlan.id.desc()).first().id
    s.commit(); s.close()
    assert client.get(f"/api/fix-plans/{pid}/previous-diff").json()["previous"] is None


def test_an_unknown_plan_is_404(client):
    assert client.get("/api/fix-plans/99999/previous-diff").status_code == 404
