"""State-machine tests for FixPlan (any plan_kind) and ChangeRequest (MVP-2.6.0)."""
import pytest

from agenticops.models import (
    CHANGE_TERMINAL_STATUSES,
    CHANGE_TRANSITIONS,
    PLAN_TRANSITIONS,
    VALID_CHANGE_STATUSES,
    VALID_PLAN_STATUSES,
    InvalidStatusTransition,
    validate_change_transition,
    validate_plan_transition,
)


def _invalid_edges(transitions: dict, valid: set) -> list[tuple[str, str]]:
    return [
        (src, dst)
        for src in transitions
        for dst in sorted(valid)
        if dst != src and dst not in transitions[src]
    ]


class TestPlanTransitions:
    @pytest.mark.parametrize("cur,new", [(s, d) for s, ds in PLAN_TRANSITIONS.items() for d in sorted(ds)])
    def test_valid_edge(self, cur, new):
        validate_plan_transition(cur, new)

    @pytest.mark.parametrize("cur,new", _invalid_edges(PLAN_TRANSITIONS, VALID_PLAN_STATUSES))
    def test_invalid_edge(self, cur, new):
        with pytest.raises(InvalidStatusTransition):
            validate_plan_transition(cur, new)

    def test_same_status_is_noop(self):
        validate_plan_transition("approved", "approved")

    def test_unknown_status_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_plan_transition("draft", "bogus")

    def test_terminal_states_have_no_exits(self):
        for s in ("executed", "failed", "rejected"):
            assert PLAN_TRANSITIONS[s] == set()

    def test_draft_can_be_auto_approved(self):
        validate_plan_transition("draft", "approved")

    def test_executed_cannot_be_reapproved(self):
        with pytest.raises(InvalidStatusTransition):
            validate_plan_transition("executed", "approved")

    def test_every_status_is_a_key(self):
        assert set(PLAN_TRANSITIONS) == VALID_PLAN_STATUSES


class TestChangeTransitions:
    @pytest.mark.parametrize("cur,new", [(s, d) for s, ds in CHANGE_TRANSITIONS.items() for d in sorted(ds)])
    def test_valid_edge(self, cur, new):
        validate_change_transition(cur, new)

    @pytest.mark.parametrize("cur,new", _invalid_edges(CHANGE_TRANSITIONS, VALID_CHANGE_STATUSES))
    def test_invalid_edge(self, cur, new):
        with pytest.raises(InvalidStatusTransition):
            validate_change_transition(cur, new)

    def test_terminal_set(self):
        assert CHANGE_TERMINAL_STATUSES == {"completed", "failed", "rolled_back", "rejected", "cancelled"}
        for s in CHANGE_TERMINAL_STATUSES:
            assert CHANGE_TRANSITIONS[s] == set()

    def test_watchdog_can_roll_review_back_to_draft(self):
        validate_change_transition("under_review", "draft")

    def test_needs_review_cannot_be_reapproved(self):
        with pytest.raises(InvalidStatusTransition):
            validate_change_transition("needs_review", "approved")

    def test_needs_review_resolves_to_completed_or_failed(self):
        validate_change_transition("needs_review", "completed")
        validate_change_transition("needs_review", "failed")

    def test_every_status_is_a_key(self):
        assert set(CHANGE_TRANSITIONS) == VALID_CHANGE_STATUSES


class TestTransitionHelpers:
    def test_transition_plan_sets_status_and_updated_at(self):
        from types import SimpleNamespace
        from agenticops.models import transition_plan
        plan = SimpleNamespace(status="draft", updated_at=None)
        transition_plan(plan, "approved")
        assert plan.status == "approved"
        assert plan.updated_at is not None

    def test_transition_plan_rejects_illegal_edge(self):
        from types import SimpleNamespace
        from agenticops.models import transition_plan
        plan = SimpleNamespace(status="executed", updated_at=None)
        with pytest.raises(InvalidStatusTransition):
            transition_plan(plan, "approved")
        assert plan.status == "executed"

    def test_transition_change_stamps_closed_at_on_terminal(self):
        from types import SimpleNamespace
        from agenticops.models import transition_change
        cr = SimpleNamespace(status="executing", updated_at=None, closed_at=None)
        transition_change(cr, "completed")
        assert cr.status == "completed"
        assert cr.closed_at is not None
        cr2 = SimpleNamespace(status="draft", updated_at=None, closed_at=None)
        transition_change(cr2, "under_review")
        assert cr2.closed_at is None
