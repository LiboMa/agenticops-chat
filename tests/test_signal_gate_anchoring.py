"""Signal Gate × IdentityResolver (spec §3.A.1 integration): new issues are anchored, merges are not
re-anchored, hints survive merges, and re-anchoring only moves forward."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, get_session
from agenticops.services import identity_resolver as ir
from agenticops.services import signal_gate as sg

CN, GLOBAL = 1, 2
CLUSTER = "agenticops-chaos-lab"


@pytest.fixture
def session(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved = {k: getattr(settings, k) for k in (
        "database_url", "signal_gate_enabled", "signal_gate_llm_enabled", "issue_exclude_patterns")}
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/anchoring.db"
    settings.signal_gate_enabled = True
    settings.signal_gate_llm_enabled = False
    settings.issue_exclude_patterns = []
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([
        CloudAccount(id=CN, name="Agenticops-CN", provider="aws", is_enabled=True,
                     credential_source_type="assume_role",
                     credentials={"role_arn": "arn:aws-cn:iam::113506788061:role/AgenticOps-CN"}),
        CloudAccount(id=GLOBAL, name="Agenticops-Global", provider="aws", is_enabled=True,
                     credential_source_type="assume_role",
                     credentials={"role_arn": "arn:aws:iam::533267047935:role/AgenticOpsRole"}),
    ])
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    for k, v in saved.items():
        setattr(settings, k, v)


def _res(s, pk, account, rtype, rid, provider="aws", name=None):
    s.add(CloudResource(id=pk, account_id=account, provider=provider, region="us-east-1", resource_type=rtype,
                        resource_id=rid, name=rid if name is None else name, tags={}, raw_data={}))
    s.commit()


def _sig(**kw):
    defaults = dict(source="webhook_prometheus", title="High CPU", description="CPU above 90%", severity="high",
                    resource_id="i-abc123", account_id="", provider="aws", issue_type="cpu_spike",
                    upstream_key="k1", kind="alert", auto_rca=False)
    defaults.update(kw)
    return sg.SignalInput(**defaults)


def _process(sig):
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
         patch("agenticops.services.notification_service.notify_issue_created"):
        return sg.process_signal(sig)


def _issue(s, issue_id):
    s.expire_all()
    return s.get(HealthIssue, issue_id)


def test_open_issue_statuses_drop_only_dismissed():
    assert "dismissed" in sg.ACTIVE_ISSUE_STATUSES
    assert sg.OPEN_ISSUE_STATUSES == tuple(s for s in sg.ACTIVE_ISSUE_STATUSES if s != "dismissed")


def test_promote_anchors_and_backfills_the_account(session):
    _res(session, 10, GLOBAL, "EC2", "i-abc123")
    issue = _issue(session, _process(_sig()).issue_id)
    assert (issue.resource_ref, issue.anchor_status, issue.account_id) == (10, ir.ANCHORED, GLOBAL)
    assert issue.anchor_candidates == {"rule": "resource_id", "candidates": []}


def test_promote_accepts_account_name_and_keeps_the_fingerprint(session):
    _res(session, 10, GLOBAL, "EC2", "i-abc123")
    _res(session, 11, CN, "EC2", "i-abc123")
    issue = _issue(session, _process(_sig(account_id="Agenticops-CN")).issue_id)
    assert (issue.resource_ref, issue.account_id) == (11, CN)
    assert issue.fingerprint == sg.compute_fingerprint_v2(
        "Agenticops-CN", "aws", "i-abc123", "cpu_spike", "k1", "High CPU")  # computed before anchoring


def test_promote_never_guesses_the_only_enabled_account(session):
    session.get(CloudAccount, CN).is_enabled = False
    session.commit()
    issue = _issue(session, _process(_sig(resource_id="sa-malibo")).issue_id)
    assert (issue.anchor_status, issue.resource_ref, issue.account_id) == (ir.UNANCHORED, None, None)


def test_an_unmanaged_account_is_not_anchored_elsewhere(session):
    _res(session, 10, GLOBAL, "EC2", "i-abc123")
    issue = _issue(session, _process(_sig(account_id="123456789012")).issue_id)
    assert (issue.anchor_status, issue.resource_ref, issue.account_id) == (ir.UNANCHORED, None, None)
    assert issue.anchor_candidates["rule"] == "unknown_account"


def test_hints_and_observed_at_are_stored(session):
    from agenticops.galaxy.rules import k8s_resource_id

    _res(session, 50, GLOBAL, "K8s_Deployment", k8s_resource_id(CLUSTER, "Deployment", "checkout", "shop"),
         provider="kubernetes", name="checkout")
    hints = {"cluster": CLUSTER, "namespace": "shop", "pod": "checkout-7d9f8b6c5-x2k4q"}
    seen = datetime(2026, 9, 28, 1, 2, 3, tzinfo=timezone.utc)
    issue = _issue(session, _process(_sig(resource_id="", hints=hints, observed_at=seen)).issue_id)
    assert (issue.resource_ref, issue.account_id, issue.anchor_status) == (50, GLOBAL, ir.ANCHORED)
    assert issue.metric_data["hints"] == hints
    assert issue.observed_at.replace(tzinfo=None) == seen.replace(tzinfo=None)


def test_merge_keeps_original_hints_and_anchor(session):
    _res(session, 10, GLOBAL, "EC2", "i-abc123")
    first = _process(_sig(hints={"region": "us-east-1"}))
    _res(session, 12, CN, "EC2", "i-abc123")  # would make a fresh resolve ambiguous
    second = _process(_sig(hints={"region": "eu-west-1"}, metric_data={"hints": {"pod": "x"}, "cpu": 99}))
    assert (second.disposition, second.issue_id) == ("merged", first.issue_id)
    issue = _issue(session, first.issue_id)
    assert issue.metric_data["hints"] == {"region": "us-east-1"}
    assert issue.metric_data["cpu"] == 99
    assert (issue.resource_ref, issue.anchor_status) == (10, ir.ANCHORED)


def test_anchoring_failure_never_loses_the_signal(session, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("resolver bug")

    monkeypatch.setattr(ir, "resolve", boom)
    decision = _process(_sig())
    assert (decision.disposition, decision.created) == ("promoted", True)
    assert _issue(session, decision.issue_id).anchor_status is None  # reanchor_open_issues retries it


def _seed_issue(s, pk, resource_id, status="open", anchor_status=ir.UNANCHORED, resource_ref=None, **kw):
    s.add(HealthIssue(id=pk, resource_id=resource_id, severity="high", source="test", title=f"t{pk}",
                      description="d", status=status, issue_type="other", anchor_status=anchor_status,
                      resource_ref=resource_ref, anchor_candidates={"rule": "seed", "candidates": []}, **kw))
    s.commit()


def test_reanchor_never_downgrades(session):
    _res(session, 10, GLOBAL, "EC2", "i-anchored")
    _seed_issue(session, 1, "i-anchored", anchor_status=ir.ANCHORED, resource_ref=10, account_id=GLOBAL)
    _seed_issue(session, 2, "i-late")                                    # its resource is scanned later
    _seed_issue(session, 3, "i-gone", anchor_status=ir.AMBIGUOUS)        # now matches nothing
    _seed_issue(session, 4, "i-late", status="resolved")                 # closed
    _seed_issue(session, 5, "i-late", status="dismissed")                # suppressed, not open
    _seed_issue(session, 6, "sa-malibo", anchor_status=None)             # backfill never reached it
    _res(session, 20, CN, "EC2", "i-late")

    assert ir.reanchor_open_issues(session) == 2
    session.commit()
    got = {i.id: (i.anchor_status, i.resource_ref, i.account_id) for i in session.query(HealthIssue)}
    assert got[1] == (ir.ANCHORED, 10, GLOBAL)
    assert got[2] == (ir.ANCHORED, 20, CN)
    assert got[3] == (ir.AMBIGUOUS, None, None)
    assert got[4] == got[5] == (ir.UNANCHORED, None, None)
    assert got[6] == (ir.UNANCHORED, None, None)
    assert session.get(HealthIssue, 3).anchor_candidates == {"rule": "seed", "candidates": []}
    assert ir.reanchor_open_issues(session) == 0  # idempotent
