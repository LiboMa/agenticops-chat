# tests/test_issue_state.py
"""transition_issue(): the single write path for HealthIssue.status (MVP-2.6.1 Plan D)."""
import json

import pytest

from agenticops.models import (
    Base, HealthIssue, InvalidStatusTransition, PipelineEvent, get_session, validate_status_transition,
)
from agenticops.services.issue_state import (
    IssueNotFound, IssueStatusConflict, advance_issue, transition_issue,
)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/issue_state.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _issue(db, status="open", trace_id="TRC-0001"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=status,
                        resource_id="r", trace_id=trace_id)
    db.add(issue)
    db.commit()
    return issue


def _events(issue_id):
    s = get_session()
    try:
        return [(e.event_type, e.stage, e.actor, e.trace_id, json.loads(e.detail))
                for e in s.query(PipelineEvent).filter_by(health_issue_id=issue_id).order_by(PipelineEvent.id)]
    finally:
        s.close()


def _status(issue_id):
    s = get_session()
    try:
        return s.get(HealthIssue, issue_id).status
    finally:
        s.close()


@pytest.mark.parametrize("src", ["fix_approved", "fix_executing", "fix_executed"])
def test_a_fix_that_did_not_hold_returns_to_root_cause_identified(src):
    validate_status_transition(src, "root_cause_identified")


def test_moves_the_row_and_logs_the_change(db):
    issue = _issue(db)
    old = transition_issue(db, issue.id, "investigating", actor="user:alice", reason="looking")
    db.commit()
    assert old == "open"
    assert _status(issue.id) == "investigating"
    assert _events(issue.id) == [("status_changed", "issue", "user:alice", "TRC-0001",
                                  {"from": "open", "to": "investigating", "reason": "looking"})]


def test_the_event_rolls_back_with_the_change(db):
    issue = _issue(db)
    transition_issue(db, issue.id, "investigating", actor="system", reason="x")
    db.rollback()
    assert _status(issue.id) == "open"
    assert _events(issue.id) == []


def test_the_loaded_row_shows_the_new_status_without_being_dirty(db):
    issue = _issue(db, status="fix_executed")
    transition_issue(db, issue.id, "resolved", actor="system", reason="verified")
    assert issue.status == "resolved"
    assert issue.resolved_at is not None
    assert issue not in db.dirty


def test_resolved_stamps_resolved_at(db):
    issue = _issue(db, status="fix_executed")
    transition_issue(db, issue.id, "resolved", actor="system", reason="verified")
    db.commit()
    s = get_session()
    try:
        assert s.get(HealthIssue, issue.id).resolved_at is not None
    finally:
        s.close()


def test_the_same_status_writes_nothing(db):
    issue = _issue(db, status="investigating")
    assert transition_issue(db, issue.id, "investigating", actor="system", reason="again") == "investigating"
    db.commit()
    assert _events(issue.id) == []


def test_an_illegal_edge_is_refused(db):
    issue = _issue(db, status="fix_approved")
    with pytest.raises(InvalidStatusTransition):
        transition_issue(db, issue.id, "open", actor="system", reason="x")
    db.commit()
    assert _status(issue.id) == "fix_approved"
    assert _events(issue.id) == []


def test_an_unknown_status_is_a_value_error(db):
    issue = _issue(db)
    with pytest.raises(ValueError):
        transition_issue(db, issue.id, "closed", actor="system", reason="x")


def test_a_missing_issue(db):
    with pytest.raises(IssueNotFound):
        transition_issue(db, 999, "investigating", actor="system", reason="x")


def test_a_concurrent_writer_wins_and_the_loser_gets_a_conflict(db):
    issue = _issue(db)
    assert issue.status == "open"  # loaded in this session
    other = get_session()
    try:
        transition_issue(other, issue.id, "acknowledged", actor="user:bob", reason="mine")
        other.commit()
    finally:
        other.close()
    with pytest.raises(IssueStatusConflict):
        transition_issue(db, issue.id, "investigating", actor="user:alice", reason="late")
    db.rollback()
    assert _status(issue.id) == "acknowledged"
    assert [e[2] for e in _events(issue.id)] == ["user:bob"]


def test_expected_is_the_compare_key(db):
    issue = _issue(db, status="open")
    with pytest.raises(IssueStatusConflict):
        transition_issue(db, issue.id, "root_cause_identified", actor="system", reason="x",
                         expected="investigating")
    db.rollback()
    assert _status(issue.id) == "open"


def test_a_conflict_is_a_409_class():
    assert issubclass(IssueStatusConflict, InvalidStatusTransition)


def test_advance_hops_an_open_issue_through_investigating(db):
    issue = _issue(db, status="open")
    assert advance_issue(db, issue.id, "root_cause_identified", actor="agent:rca", reason="saved") is None
    db.commit()
    assert _status(issue.id) == "root_cause_identified"
    assert [(e[4]["from"], e[4]["to"]) for e in _events(issue.id)] == [
        ("open", "investigating"), ("investigating", "root_cause_identified")]


def test_advance_takes_a_direct_edge_without_a_hop(db):
    issue = _issue(db, status="root_cause_identified")
    assert advance_issue(db, issue.id, "fix_planned", actor="agent:sre", reason="plan") is None
    db.commit()
    assert [(e[4]["from"], e[4]["to"]) for e in _events(issue.id)] == [("root_cause_identified", "fix_planned")]


def test_advance_does_not_hop_when_the_hop_cannot_get_there(db):
    issue = _issue(db, status="open")
    refusal = advance_issue(db, issue.id, "fix_approved", actor="agent:auto-pipeline", reason="approved")
    db.commit()
    assert refusal and "fix_approved" in refusal
    assert _status(issue.id) == "open"
    assert _events(issue.id) == []


def test_advance_returns_the_refusal_instead_of_raising(db):
    issue = _issue(db, status="resolved")
    refusal = advance_issue(db, issue.id, "fix_executing", actor="system", reason="late")
    db.commit()
    assert refusal and "resolved" in refusal
    assert _status(issue.id) == "resolved"
    assert advance_issue(db, 999, "fix_planned", actor="system", reason="x") == "HealthIssue #999 not found"
