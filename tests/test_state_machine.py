"""Tests for HealthIssue state machine enforcement."""

import sys
sys.path.insert(0, "src")

import pytest

from agenticops.models import (
    VALID_ISSUE_STATUSES,
    InvalidStatusTransition,
    _ISSUE_TRANSITIONS,
    validate_status_transition,
    HealthIssue,
    Base,
    get_session,
)


# ---------------------------------------------------------------------------
# validate_status_transition — valid transitions
# ---------------------------------------------------------------------------

class TestValidTransitions:
    """Every entry in _ISSUE_TRANSITIONS should pass validation."""

    @pytest.mark.parametrize(
        "current,new",
        [
            (src, dst)
            for src, dsts in _ISSUE_TRANSITIONS.items()
            for dst in dsts
        ],
        ids=lambda val: str(val),
    )
    def test_valid_transition_succeeds(self, current, new):
        # Should not raise
        validate_status_transition(current, new)

    def test_open_to_investigating(self):
        validate_status_transition("open", "investigating")

    def test_open_to_acknowledged(self):
        validate_status_transition("open", "acknowledged")

    def test_open_to_resolved(self):
        validate_status_transition("open", "resolved")

    def test_investigating_to_root_cause_identified(self):
        validate_status_transition("investigating", "root_cause_identified")

    def test_fix_planned_to_fix_approved(self):
        validate_status_transition("fix_planned", "fix_approved")

    def test_fix_approved_to_fix_executing(self):
        validate_status_transition("fix_approved", "fix_executing")

    def test_fix_executing_to_fix_executed(self):
        validate_status_transition("fix_executing", "fix_executed")

    def test_fix_executed_to_resolved(self):
        validate_status_transition("fix_executed", "resolved")


# ---------------------------------------------------------------------------
# validate_status_transition — invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    """Transitions not in the allowed map must raise InvalidStatusTransition."""

    def test_open_to_fix_executed(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("open", "fix_executed")

    def test_open_to_fix_planned(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("open", "fix_planned")

    def test_open_to_fix_approved(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("open", "fix_approved")

    def test_open_to_fix_executing(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("open", "fix_executing")

    def test_open_to_root_cause_identified(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("open", "root_cause_identified")

    def test_resolved_to_open(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("resolved", "open")

    def test_resolved_to_investigating(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("resolved", "investigating")

    def test_resolved_to_fix_planned(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("resolved", "fix_planned")

    def test_fix_executed_to_open(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("fix_executed", "open")

    def test_fix_executed_to_investigating(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("fix_executed", "investigating")

    def test_fix_approved_to_open(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("fix_approved", "open")

    def test_fix_planned_to_investigating(self):
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("fix_planned", "investigating")

    @pytest.mark.parametrize(
        "current,new",
        [
            ("resolved", "open"),
            ("resolved", "investigating"),
            ("resolved", "acknowledged"),
            ("resolved", "root_cause_identified"),
            ("resolved", "fix_planned"),
            ("resolved", "fix_approved"),
            ("resolved", "fix_executing"),
            ("resolved", "fix_executed"),
        ],
    )
    def test_resolved_blocks_all_outgoing(self, current, new):
        """Terminal state 'resolved' cannot transition to any other status."""
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(current, new)


# ---------------------------------------------------------------------------
# validate_status_transition — no-op (same status)
# ---------------------------------------------------------------------------

class TestNoOpTransitions:
    """Transitioning to the same status should succeed silently."""

    @pytest.mark.parametrize("status", sorted(VALID_ISSUE_STATUSES))
    def test_same_status_is_noop(self, status):
        # Should not raise
        validate_status_transition(status, status)


# ---------------------------------------------------------------------------
# validate_status_transition — invalid status values
# ---------------------------------------------------------------------------

class TestInvalidStatusValues:
    """Unknown status strings must raise ValueError."""

    def test_invalid_new_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status_transition("open", "nonexistent")

    def test_invalid_new_status_empty(self):
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status_transition("open", "")

    def test_invalid_new_status_numeric(self):
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status_transition("open", "123")

    def test_unknown_current_status_with_valid_new(self):
        """If current status is unknown, allowed set is empty -> InvalidStatusTransition."""
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("unknown_state", "open")

    def test_both_statuses_invalid(self):
        """Invalid new status is checked first (before current lookup)."""
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status_transition("bogus", "also_bogus")


# ---------------------------------------------------------------------------
# Transition map completeness
# ---------------------------------------------------------------------------

class TestTransitionMapCompleteness:
    """Every status in VALID_ISSUE_STATUSES should appear in _ISSUE_TRANSITIONS."""

    def test_all_statuses_have_transition_entry(self):
        for status in VALID_ISSUE_STATUSES:
            assert status in _ISSUE_TRANSITIONS, (
                f"Status '{status}' is in VALID_ISSUE_STATUSES but missing "
                f"from _ISSUE_TRANSITIONS"
            )

    def test_every_non_terminal_status_has_outgoing(self):
        """Every status except 'resolved' should have at least one outgoing transition."""
        for status in VALID_ISSUE_STATUSES:
            if status == "resolved":
                assert _ISSUE_TRANSITIONS[status] == set()
            else:
                assert len(_ISSUE_TRANSITIONS[status]) > 0, (
                    f"Non-terminal status '{status}' has no outgoing transitions"
                )

    def test_all_transition_targets_are_valid(self):
        """Every target in _ISSUE_TRANSITIONS must be in VALID_ISSUE_STATUSES."""
        for src, dsts in _ISSUE_TRANSITIONS.items():
            for dst in dsts:
                assert dst in VALID_ISSUE_STATUSES, (
                    f"Transition target '{dst}' (from '{src}') is not a valid status"
                )

    def test_resolved_is_terminal(self):
        assert _ISSUE_TRANSITIONS["resolved"] == set()


# ---------------------------------------------------------------------------
# InvalidStatusTransition is a ValueError subclass
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    def test_invalid_status_transition_is_value_error(self):
        assert issubclass(InvalidStatusTransition, ValueError)

    def test_catch_as_value_error(self):
        with pytest.raises(ValueError):
            validate_status_transition("open", "fix_executed")


# ---------------------------------------------------------------------------
# Integration: update_health_issue_status tool
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


class TestUpdateHealthIssueStatusTool:
    """Integration tests for metadata_tools.update_health_issue_status."""

    def _create_issue(self, session, status="open"):
        issue = HealthIssue(
            resource_id="i-test123",
            title="Test Issue",
            description="A test issue",
            severity="high",
            status=status,
            source="test",
        )
        session.add(issue)
        session.commit()
        return issue.id

    def test_valid_transition_via_tool(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session)
        result = update_health_issue_status(issue_id, "investigating")
        assert "open -> investigating" in result

    def test_invalid_transition_returns_error_message(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session)
        result = update_health_issue_status(issue_id, "fix_executed")
        assert "Status transition rejected" in result

    def test_nonexistent_issue(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        result = update_health_issue_status(99999, "investigating")
        assert "not found" in result

    def test_resolved_sets_resolved_at(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session)
        update_health_issue_status(issue_id, "resolved")

        session = get_session()
        issue = session.query(HealthIssue).get(issue_id)
        assert issue.resolved_at is not None
        session.close()

    def test_case_insensitive_status(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session)
        result = update_health_issue_status(issue_id, "INVESTIGATING")
        assert "open -> investigating" in result

    def test_noop_transition_via_tool(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session, status="investigating")
        result = update_health_issue_status(issue_id, "investigating")
        # No-op: same status, should succeed (status unchanged)
        assert "investigating -> investigating" in result

    def test_note_included_in_result(self, db_session):
        from agenticops.tools.metadata_tools import update_health_issue_status

        issue_id = self._create_issue(db_session)
        result = update_health_issue_status(issue_id, "investigating", note="started triage")
        assert "started triage" in result
