# tests/test_dismissed_semantics.py
"""dismissed suppresses re-alerts but is not open (MVP-2.6.1 Plan D, spec §3.D.6)."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agenticops.models import Base, HealthIssue, SecuritySnapshot, get_session
from agenticops.services import signal_gate as sg
from agenticops.services.issue_state import transition_issue


@pytest.fixture
def session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved = {k: getattr(settings, k) for k in (
        "database_url", "signal_gate_enabled", "signal_gate_llm_enabled", "issue_exclude_patterns")}
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/dismissed.db"
    settings.signal_gate_enabled = True
    settings.signal_gate_llm_enabled = False
    settings.issue_exclude_patterns = []
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None
    for k, v in saved.items():
        setattr(settings, k, v)


def _seed(s, pk, status, **kw):
    s.add(HealthIssue(id=pk, resource_id="i-abc123", severity="high", source="test", title=f"t{pk}",
                      description="d", status=status, issue_type="other", **kw))
    s.commit()


def _sig():
    return sg.SignalInput(source="webhook_prometheus", title="High CPU", description="CPU above 90%",
                          severity="high", resource_id="i-abc123", account_id="", provider="aws",
                          issue_type="cpu_spike", upstream_key="k1", kind="alert", auto_rca=False)


def test_the_two_sets_differ_only_by_dismissed():
    assert "dismissed" in sg.SUPPRESSING_ISSUE_STATUSES
    assert sg.ACTIVE_ISSUE_STATUSES == sg.SUPPRESSING_ISSUE_STATUSES  # the old name still imports
    assert set(sg.SUPPRESSING_ISSUE_STATUSES) - set(sg.OPEN_ISSUE_STATUSES) == {"dismissed"}


def test_a_dismissed_issue_is_not_a_gray_zone_candidate(session):
    _seed(session, 1, "open")
    _seed(session, 2, "dismissed")
    got = sg._gray_zone_candidates(session, _sig(), datetime.now(timezone.utc))
    assert [i.id for i in got] == [1]


def test_a_repeat_of_a_dismissed_alert_is_still_suppressed(session):
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        first = sg.process_signal(_sig())
        transition_issue(session, first.issue_id, "dismissed", actor="user:alice", reason="false positive")
        session.commit()
        second = sg.process_signal(_sig())
    assert first.created
    assert (second.disposition, second.reason, second.issue_id) == ("merged", "exact_fingerprint", first.issue_id)
    assert second.issue_status == "dismissed"


def test_the_security_open_count_leaves_out_dismissed(session):
    from agenticops.services import security_service as svc

    session.add(SecuritySnapshot(account_id="acct-a", provider="aws", overall_score=75.0,
                                 category_scores={}, exposure_paths=[]))
    session.commit()
    for pk, status in ((1, "open"), (2, "dismissed"), (3, "resolved"), (4, "fix_planned")):
        _seed(session, pk, status, detected_by="security_posture")
    assert svc.security_summary()["accounts"][0]["open_findings"] == 2
