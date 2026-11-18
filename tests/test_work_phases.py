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
                       auto_run_in_flight=inp.get("autoRunInFlight", False), rca_stopped=inp.get("rcaStopped", False), **kw)
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
