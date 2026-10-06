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
    p = wp.issue_phase(inp["status"], threshold=inp.get("threshold"),
                       auto_run_in_flight=inp.get("autoRunInFlight", False), **kw)
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
