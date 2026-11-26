"""One UTC conversion and one «…Z» rendering (review of MVP-2.9.0, ④): `utils/timeutils.as_utc` / `iso_z` replace
the copies 2.9.0 wrote in ten modules. The references below are those copies, word for word: the new helpers give
the same answer for everything those modules are handed — naive UTC from the database, aware UTC from the clock."""
from datetime import datetime, timedelta, timezone

import pytest

NAIVE = datetime(2026, 11, 26, 9, 30, 5, 123456)
CASES = [NAIVE, NAIVE.replace(microsecond=0), NAIVE.replace(tzinfo=timezone.utc),
         NAIVE.replace(microsecond=0, tzinfo=timezone.utc),
         NAIVE.replace(tzinfo=timezone(timedelta(hours=8)))]            # another zone: the same moment, in UTC


def _old_iso(ts):                               # activity / ui_events / attention_snooze / readiness / security_service
    if ts is None:
        return None
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _old_galaxy(ts):                            # galaxy/api._utc
    if ts is None:
        return None
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


@pytest.mark.parametrize("ts", CASES + [None])
def test_iso_z_is_what_the_copies_wrote(ts):
    from agenticops.utils.timeutils import iso_z
    assert iso_z(ts) == _old_iso(ts)
    assert iso_z(ts, timespec="seconds") == _old_galaxy(ts)


@pytest.mark.parametrize("ts", CASES)
def test_as_utc_is_the_same_moment_in_utc(ts):
    from agenticops.utils.timeutils import as_utc
    got = as_utc(ts)
    assert got.tzinfo is timezone.utc
    assert got == (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))
    assert as_utc(None) is None


def test_no_2_9_0_module_keeps_its_own_copy():
    """The modules that had one now call timeutils (agent_steps keeps its «+00:00» rendering: its API answers so)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"
    for rel in ("services/activity.py", "services/ui_events.py", "services/attention_snooze.py",
                "services/readiness.py", "services/security_service.py", "services/plan_content.py",
                "galaxy/api.py", "services/agent_steps.py"):
        src = (root / rel).read_text()
        assert "replace(tzinfo=timezone.utc)" not in src and 'replace("+00:00", "Z")' not in src, rel
