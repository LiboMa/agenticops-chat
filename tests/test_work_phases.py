"""services/work_phases is the server's copy of the issue/change pages' "who it waits on" (MVP-2.7.0 S3).
The fixtures are shared with frontend src/__tests__/workPhaseParity.test.ts, so the two copies cannot drift."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from agenticops.services import work_phases as wp

FIX = Path(__file__).parent / "fixtures"
PHASES = json.loads((FIX / "work_item_phase_cases.json").read_text())
AUTO = json.loads((FIX / "auto_run_cases.json").read_text())


def _ts(s):
    return None if s is None else datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.mark.parametrize("case", PHASES["issue"], ids=lambda c: c["name"])
def test_issue_phase_matches_the_page(case):
    inp = case["input"]
    kw = {py: inp[js] for js, py in (("rca", "rca"), ("plan", "plan"), ("latestRun", "latest_run")) if js in inp}
    p = wp.issue_phase(inp["status"], threshold=inp.get("threshold"), auto_fix_enabled=inp.get("autoFixEnabled"),
                       auto_run_in_flight=inp.get("autoRunInFlight", False), rca_stopped=inp.get("rcaStopped", False),
                       reopened=inp.get("reopened", False), plan_stopped=inp.get("planStopped", False), **kw)
    e = case["expect"]
    assert (p.sub, p.waiting_for, p.primary) == (e["sub"], e["waitingFor"], e["primary"])


@pytest.mark.parametrize("case", PHASES["change"], ids=lambda c: c["name"])
def test_change_phase_matches_the_page(case):
    p = wp.change_phase(case["input"])
    e = case["expect"]
    assert (p.sub, p.waiting_for, p.primary) == (e["sub"], e["waitingFor"], e["primary"])


@pytest.mark.parametrize("case", AUTO["in_flight"], ids=lambda c: c["name"])
def test_in_flight_auto_run(case):
    got = wp.in_flight_auto_run(case["events"], case["plan_id"], timeout_seconds=case["timeout_seconds"],
                                now=_ts(case["now"]))
    assert got == _ts(case["expect"])


@pytest.mark.parametrize("case", AUTO["not_queued"], ids=lambda c: c["name"])
def test_not_queued_from(case):
    assert wp.not_queued_from(case["events"], case["plan"]["id"], case["plan"]["approved_at"]) == _ts(case["expect"])


def test_current_fix_plan_prefers_the_newest_open_plan():
    plans = [{"id": 1, "status": "rejected", "created_at": "2026-10-06T10:00:00Z"},
             {"id": 2, "status": "draft", "created_at": "2026-10-05T10:00:00Z"},
             {"id": 3, "status": "executed", "created_at": "2026-10-06T11:00:00Z"}]
    assert wp.current_fix_plan(plans)["id"] == 2
    assert wp.current_fix_plan([plans[0], plans[2]])["id"] == 3
    assert wp.current_fix_plan([]) is None


def test_orm_event_details_are_parsed():
    class E:  # an ORM PipelineEvent: detail is JSON text, created_at naive UTC
        def __init__(self, i, t, d, at):
            self.id, self.event_type, self.detail, self.created_at = i, t, d, at
    ev = [E(1, "execution_started", '{"plan_id": 7}', datetime(2026, 10, 6, 10, 0))]
    assert wp.in_flight_auto_run(ev, 7, timeout_seconds=3600, now=_ts("2026-10-06T10:01:00Z")) == _ts("2026-10-06T10:00:00Z")
    assert wp.in_flight_auto_run([E(1, "execution_started", "not json", datetime(2026, 10, 6, 10, 0))], 7,
                                 timeout_seconds=3600, now=_ts("2026-10-06T10:01:00Z")) is None


# ── a diagnosis that stopped (MVP-2.9.0 N11) ────────────────────────────────

def _ev(event_type, at, status="completed"):
    return {"event_type": event_type, "status": status, "created_at": at}


@pytest.mark.parametrize("status, events, want", [
    # it ended — failed, timed out, or «completed» without moving the issue — and nothing started after it
    ("investigating", [_ev("rca_started", "2026-11-18T03:00:00Z", "started"), _ev("rca_completed", "2026-11-18T03:15:00Z", "failed")], "2026-11-18T03:15:00Z"),
    ("open", [_ev("rca_completed", "2026-11-18T03:15:00Z", "failed")], "2026-11-18T03:15:00Z"),                # no start on record
    ("acknowledged", [_ev("rca_started", "2026-11-18T03:00:00Z"), _ev("rca_completed", "2026-11-18T03:00:00Z")], "2026-11-18T03:00:00Z"),
    # a newer one has started: it is under way
    ("investigating", [_ev("rca_completed", "2026-11-18T03:15:00Z", "failed"), _ev("rca_started", "2026-11-18T03:20:00Z", "started")], None),
    # never diagnosed, or only started
    ("open", [], None),
    ("investigating", [_ev("rca_started", "2026-11-18T03:00:00Z", "started")], None),
    # past diagnosis: not this rule's question
    ("root_cause_identified", [_ev("rca_completed", "2026-11-18T03:15:00Z", "failed")], None),
    ("fix_planned", [_ev("rca_completed", "2026-11-18T03:15:00Z", "failed")], None),
    # other events do not count
    ("investigating", [_ev("execution_completed", "2026-11-18T03:15:00Z", "failed")], None),
])
def test_when_a_diagnosis_stopped(status, events, want):
    assert wp.rca_stopped_at(status, events) == _ts(want)


@pytest.mark.parametrize("events, now, limit, want", [
    # it started, never ended, and its time limit passed long ago: the process that ran it is gone — it will not
    # end. It counts as stopped from the moment it should have ended at the latest.
    ([_ev("rca_started", "2026-08-30T03:00:00Z", "started")], "2026-11-18T03:00:00Z", 900, "2026-08-30T03:15:00Z"),
    # still inside its limit: under way
    ([_ev("rca_started", "2026-11-18T02:50:00Z", "started")], "2026-11-18T03:00:00Z", 900, None),
    # no limit configured: nothing says it should have ended
    ([_ev("rca_started", "2026-08-30T03:00:00Z", "started")], "2026-11-18T03:00:00Z", 0, None),
    # an older one failed, a newer one started and outlived its limit: stopped at the newer one's limit
    ([_ev("rca_completed", "2026-11-17T01:00:00Z", "failed"), _ev("rca_started", "2026-11-17T02:00:00Z", "started")],
     "2026-11-18T03:00:00Z", 900, "2026-11-17T02:15:00Z"),
    # it did end: the end is the time, limit or not
    ([_ev("rca_started", "2026-11-18T01:00:00Z", "started"), _ev("rca_completed", "2026-11-18T01:05:00Z", "failed")],
     "2026-11-18T03:00:00Z", 900, "2026-11-18T01:05:00Z"),
])
def test_a_diagnosis_that_never_ended_and_is_long_past_its_limit_has_stopped(events, now, limit, want):
    assert wp.rca_stopped_at("investigating", events, now=_ts(now), limit_seconds=limit) == _ts(want)


def test_a_status_move_after_the_diagnosis_voids_it():
    """Found on a copy of the local database: an issue diagnosed, planned, dismissed and reopened weeks later is
    `open` again — its old diagnosis ended long before, but it is not why the issue stands here now."""
    ended = [_ev("rca_started", "2026-10-04T00:00:00Z", "started"), _ev("rca_completed", "2026-10-04T00:03:00Z")]
    assert wp.rca_stopped_at("open", ended) == _ts("2026-10-04T00:03:00Z")
    assert wp.rca_stopped_at("open", ended, moved_at=_ts("2026-11-17T09:25:00Z")) is None             # reopened since
    assert wp.rca_stopped_at("open", ended, moved_at=_ts("2026-10-04T00:01:00Z")) == _ts("2026-10-04T00:03:00Z")   # moved before it ended
    orphan = [_ev("rca_started", "2026-08-30T03:00:00Z", "started")]
    kw = {"now": _ts("2026-11-18T03:00:00Z"), "limit_seconds": 900}
    assert wp.rca_stopped_at("open", orphan, moved_at=_ts("2026-09-10T00:00:00Z"), **kw) is None      # reopened since it should have ended
    assert wp.rca_stopped_at("investigating", orphan, moved_at=_ts("2026-08-30T03:00:09Z"), **kw) == _ts("2026-08-30T03:15:00Z")


# ── nobody's turn: a reopened issue, a plan run that left no plan (MVP-2.9.0 N26) ───────────────────────────

def _move(frm, to, at):
    return {"event_type": "status_changed", "status": "completed", "created_at": at, "detail": {"from": frm, "to": to}}


@pytest.mark.parametrize("status, events, want", [
    # dismissed, then reopened: nothing diagnoses it again by itself
    ("open", [_move("investigating", "dismissed", "2026-11-10T00:00:00Z"), _move("dismissed", "open", "2026-11-17T09:25:00Z")], "2026-11-17T09:25:00Z"),
    # … and moved among the diagnosing statuses since (a person acknowledged it): reopened still, since the reopening
    ("acknowledged", [_move("dismissed", "open", "2026-11-17T09:25:00Z"), _move("open", "acknowledged", "2026-11-17T10:00:00Z")], "2026-11-17T09:25:00Z"),
    # a diagnosis was started after the reopening: its turn (if that one stopped, that is the other rule's answer)
    ("investigating", [_move("dismissed", "open", "2026-11-17T09:25:00Z"), _ev("rca_started", "2026-11-17T09:30:00Z", "started")], None),
    # a diagnosis from BEFORE the dismissal does not count
    ("open", [_ev("rca_started", "2026-10-04T00:00:00Z", "started"), _ev("rca_completed", "2026-10-04T00:03:00Z"),
              _move("root_cause_identified", "dismissed", "2026-11-10T00:00:00Z"), _move("dismissed", "open", "2026-11-17T09:25:00Z")], "2026-11-17T09:25:00Z"),
    # never dismissed: only ever open, or moved among the diagnosing statuses, or back from somewhere else
    ("open", [], None),
    ("open", [_move("open", "acknowledged", "2026-11-17T09:00:00Z"), _move("acknowledged", "open", "2026-11-17T09:25:00Z")], None),
    ("open", [_move("root_cause_identified", "open", "2026-11-17T09:25:00Z")], None),
    # dismissed and reopened, dismissed and reopened again: the newest reopening
    ("open", [_move("dismissed", "open", "2026-10-01T00:00:00Z"), _move("open", "dismissed", "2026-10-02T00:00:00Z"),
              _move("dismissed", "open", "2026-11-17T09:25:00Z")], "2026-11-17T09:25:00Z"),
    # past diagnosis, or dismissed again: not this rule's question
    ("root_cause_identified", [_move("dismissed", "open", "2026-11-17T09:25:00Z")], None),
    ("dismissed", [_move("dismissed", "open", "2026-11-17T09:25:00Z"), _move("open", "dismissed", "2026-11-18T00:00:00Z")], None),
    # a move whose record does not say where from: not known to be a reopening
    ("open", [{"event_type": "status_changed", "status": "completed", "created_at": "2026-11-17T09:25:00Z", "detail": None}], None),
    # the detail as the database stores it: a JSON string
    ("open", [{"event_type": "status_changed", "status": "completed", "created_at": "2026-11-17T09:25:00Z",
               "detail": '{"from": "dismissed", "to": "open", "reason": "x"}'}], "2026-11-17T09:25:00Z"),
])
def test_when_an_issue_was_reopened_and_not_diagnosed_since(status, events, want):
    assert wp.reopened_at(status, events) == _ts(want)


def _plan_ev(status, at, reason=None):
    return {"event_type": "fix_plan_requested", "status": status, "created_at": at, "detail": {"reason": reason} if reason else None}


@pytest.mark.parametrize("events, want", [
    # the plan run ended and left no plan — it failed, or the agent gave up
    ([_plan_ev("started", "2026-11-18T03:00:00Z"), _plan_ev("failed", "2026-11-18T03:10:00Z", "no_plan")], "2026-11-18T03:10:00Z"),
    ([_plan_ev("failed", "2026-11-18T03:10:00Z", "agent error")], "2026-11-18T03:10:00Z"),          # no start on record: asked for in a chat
    # a newer run has started: it is under way
    ([_plan_ev("failed", "2026-11-18T03:10:00Z"), _plan_ev("started", "2026-11-18T03:20:00Z")], None),
    # a plan was written after it ended: that failure is not where the issue stands
    ([_plan_ev("failed", "2026-11-18T03:10:00Z"), _ev("fix_plan_created", "2026-11-18T03:30:00Z")], None),
    ([_plan_ev("failed", "2026-11-18T03:10:00Z"), _ev("fix_plan_updated", "2026-11-18T03:30:00Z")], None),
    # … a plan written BEFORE it does not undo it (an older plan, sent back since)
    ([_ev("fix_plan_created", "2026-11-18T02:00:00Z"), _plan_ev("started", "2026-11-18T03:00:00Z"),
      _plan_ev("failed", "2026-11-18T03:10:00Z")], "2026-11-18T03:10:00Z"),
    # never asked for, or only started
    ([], None),
    ([_plan_ev("started", "2026-11-18T03:00:00Z")], None),
    # other events do not count
    ([_ev("rca_completed", "2026-11-18T03:10:00Z", "failed")], None),
])
def test_when_a_plan_run_ended_without_a_plan(events, want):
    assert wp.plan_stopped_at("root_cause_identified", events) == _ts(want)


def test_a_plan_run_is_only_one_statuss_question():
    ended = [_plan_ev("started", "2026-11-18T03:00:00Z"), _plan_ev("failed", "2026-11-18T03:10:00Z", "no_plan")]
    for status in ("open", "investigating", "fix_planned", "fix_approved", "resolved", "dismissed"):
        assert wp.plan_stopped_at(status, ended) is None


@pytest.mark.parametrize("events, now, limit, want", [
    # it started, never ended, and its limit passed: the process that ran it is gone
    ([_plan_ev("started", "2026-08-30T03:00:00Z")], "2026-11-18T03:00:00Z", 900, "2026-08-30T03:15:00Z"),
    ([_plan_ev("started", "2026-11-18T02:50:00Z")], "2026-11-18T03:00:00Z", 900, None),                 # inside its limit
    ([_plan_ev("started", "2026-08-30T03:00:00Z")], "2026-11-18T03:00:00Z", 0, None),                   # no limit: nothing says it should have ended
    # it started and a plan was written since: it did end, with a plan
    ([_plan_ev("started", "2026-08-30T03:00:00Z"), _ev("fix_plan_created", "2026-08-30T03:05:00Z")], "2026-11-18T03:00:00Z", 900, None),
])
def test_a_plan_run_that_never_ended_and_is_past_its_limit_has_stopped(events, now, limit, want):
    assert wp.plan_stopped_at("root_cause_identified", events, now=_ts(now), limit_seconds=limit) == _ts(want)


def test_a_status_move_after_the_plan_run_voids_it():
    """Diagnosed again since: the issue stands at «diagnosed» for another reason than that old plan run."""
    ended = [_plan_ev("started", "2026-11-18T03:00:00Z"), _plan_ev("failed", "2026-11-18T03:10:00Z", "no_plan")]
    assert wp.plan_stopped_at("root_cause_identified", ended, moved_at=_ts("2026-11-18T04:00:00Z")) is None
    assert wp.plan_stopped_at("root_cause_identified", ended, moved_at=_ts("2026-11-18T02:59:00Z")) == _ts("2026-11-18T03:10:00Z")
