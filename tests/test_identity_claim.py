"""A legacy issue with account_id NULL stays inside the account its signal stated (Plan A final review I-1).

The claim, most trusted first: the issue's own account, the audit claim, the earliest promoted Signal row
(alert_events). An empty ledger account means the signal stated none — the spec's no-account search. No
ledger row at all means the claim is unknown: nothing is searched across accounts (rule account_unknown)."""
from datetime import datetime, timedelta

import pytest

from agenticops.models import AlertEvent, Base, CloudAccount, CloudResource, HealthIssue, get_session
from agenticops.services import identity_resolver as ir

A, B = 1, 2
T0 = datetime(2026, 9, 1, 12, 0, 0)


@pytest.fixture
def session(tmp_path):
    """acct-a and acct-b, both enabled; RDS database-demo is in acct-b's inventory only."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/claim.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([
        CloudAccount(id=A, name="acct-a", provider="aws", is_enabled=True, credentials={}),
        CloudAccount(id=B, name="acct-b", provider="aws", is_enabled=True, credentials={}),
    ])
    s.add(CloudResource(id=20, account_id=B, provider="aws", region="us-east-1", resource_type="RDS",
                        resource_id="database-demo", name="database-demo", tags={}, raw_data={}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _issue(s, pk=1, anchor_status=None, anchor_candidates=None, account_id=None):
    s.add(HealthIssue(id=pk, resource_id="database-demo", severity="high", source="test", title=f"t{pk}",
                      description="d", status="open", issue_type="other", account_id=account_id,
                      anchor_status=anchor_status, anchor_candidates=anchor_candidates))
    s.commit()


def _signal(s, issue_id, account, disposition="promoted", minutes=0):
    s.add(AlertEvent(source="webhook_prometheus", external_id=f"e{issue_id}-{minutes}", severity="high",
                     title="t", health_issue_id=issue_id, account_id=account, disposition=disposition,
                     received_at=T0 + timedelta(minutes=minutes)))
    s.commit()


def _backfill(s):
    import agenticops.models as models_mod

    models_mod._backfill_anchors_2_6_1(models_mod.get_engine())
    s.expire_all()


def _reanchor(s):
    changed = ir.reanchor_open_issues(s)
    s.commit()
    s.expire_all()
    return changed


def _state(s, pk=1):
    issue = s.get(HealthIssue, pk)
    return issue.anchor_status, issue.account_id, issue.resource_ref, (issue.anchor_candidates or {}).get("rule")


# ── the three claim cases, through the 2.6.1 backfill and through re-anchoring ──

STATED_A = (ir.UNANCHORED, A, None, "none")               # searched in acct-a only; back-fills acct-a
UNKNOWN = (ir.UNANCHORED, None, None, "account_unknown")  # no ledger row: never searched across accounts
STATED_NONE = (ir.ANCHORED, B, 20, "resource_id")         # the spec's no-account path: unique hit in acct-b


@pytest.mark.parametrize("run", [_backfill, _reanchor], ids=["backfill", "reanchor"])
@pytest.mark.parametrize("ledger,expected", [
    ("acct-a", STATED_A),
    (None, UNKNOWN),
    ("", STATED_NONE),
], ids=["ledger-claim", "no-ledger-row", "empty-ledger-account"])
def test_a_null_account_issue_follows_the_ledger_claim(session, run, ledger, expected):
    _issue(session)
    if ledger is not None:
        _signal(session, 1, ledger)
    run(session)
    assert _state(session) == expected


def test_an_account_unknown_issue_stays_unchanged_on_the_next_reanchor(session):
    _issue(session)
    assert _reanchor(session) == 1
    assert _state(session) == UNKNOWN
    assert _reanchor(session) == 0
    assert _state(session) == UNKNOWN


def test_the_audit_claim_wins_over_the_ledger(session):
    """A failed anchor recorded the stated account in the audit (signal_gate._promote)."""
    _issue(session, anchor_candidates={"rule": "error", "candidates": [{"account": "acct-a", "reason": "error"}]})
    _signal(session, 1, "")
    _reanchor(session)
    assert _state(session) == STATED_A


# ── which ledger rows are the claim ──


def test_the_earliest_promoted_row_is_the_claim(session):
    _signal(session, 1, "acct-b", minutes=5)
    _signal(session, 1, "acct-a", minutes=1)
    _issue(session)
    _backfill(session)
    assert _state(session) == STATED_A


def test_a_merged_row_is_never_the_claim(session):
    _signal(session, 1, "acct-b", disposition="merged", minutes=1)
    _signal(session, 1, "acct-a", minutes=5)
    _issue(session)
    _backfill(session)
    assert _state(session) == STATED_A


@pytest.mark.parametrize("disposition", ["noise", "error"])
def test_noise_and_error_rows_are_never_the_claim(session, disposition):
    _signal(session, 1, "", disposition=disposition)
    _issue(session)
    _backfill(session)
    assert _state(session) == UNKNOWN


def test_a_signal_of_another_issue_is_not_the_claim(session):
    _signal(session, 2, "", minutes=0)
    _signal(session, 1, "acct-a", minutes=1)
    _issue(session)
    _backfill(session)
    assert _state(session) == STATED_A
