"""Assert-mode E2E: inject → perceive → analyze → resolve → record → restore.

Requires a live cluster + a port-forwarded app (see run-e2e.sh). Not part of
offline CI. Each phase failure raises PhaseTimeout naming the failed phase.
"""
import time

import pytest

from client import PhaseTimeout
from conftest import run_chaos, verify_fix, restore_and_wait


def test_four_phases(client, assert_scenario, request):
    sc = assert_scenario
    # Clean start
    restore_and_wait(sc)

    try:
        # inject the fault
        run_chaos(sc["inject"])
        # Give the fault a moment to manifest before seeding perception.
        time.sleep(10)

        # ---- 感知 (perceive): seed a CloudWatch alert, then assert an issue appears
        client.send_cloudwatch_alert(sc["perceive"]["alert"])
        issue_id = client.wait_for_issue(
            sc["perceive"]["title_pattern"], timeout_s=sc["timeout_perceive_s"])

        # ---- 分析 (analyze): RCA attached
        analyze_deadline = time.monotonic() + 180
        while time.monotonic() < analyze_deadline and not client.has_rca(issue_id):
            time.sleep(5)
        assert client.has_rca(issue_id), f"[analyze] no RCA for issue {issue_id}"

        # ---- 解决 (resolve): issue resolved AND a fix plan executed AND cluster fixed
        status = client.wait_for_status(
            issue_id, {"resolved"}, timeout_s=sc["timeout_resolve_s"])
        assert status == "resolved"
        plan = client.get_fix_plan(issue_id)
        assert plan is not None, f"[resolve] no fix plan for issue {issue_id}"
        ok, detail = verify_fix(sc["expect_fix"])
        assert ok, f"[resolve] cluster not actually fixed: {detail}"

        # ---- 记录 (record): timeline has fix/resolve events
        timeline = client.get_timeline(issue_id)
        etypes = " ".join(str(e.get("event_type", "")) for e in timeline).lower()
        assert timeline, f"[record] empty timeline for issue {issue_id}"
        assert ("resolve" in etypes or "fix" in etypes or "execut" in etypes), \
            f"[record] no fix/resolve events in timeline: {etypes}"
    finally:
        restore_and_wait(sc)
