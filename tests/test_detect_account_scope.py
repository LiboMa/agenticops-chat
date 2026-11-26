"""A detection of one account sees and records only that account (MVP-2.9.0 N32).

Found in the issue reset of 2026-11-23, on every database: the parallel per-account detection's
`get_managed_resources` returned the managed rows of EVERY enabled account, first 50 — all of them the China
account's. The Global account's worker probed those China-region resources with Global credentials, was refused
(InvalidClientTokenId) and opened a false «credentials invalid, monitoring blind» issue; its own 1,467 managed
resources were never checked. And `create_health_issue` stated no account, so an issue about `root`, an IAM user or
anything else not in the inventory had none (6 of 9 detection issues on the local database).

Now each worker runs bound to its account (`RunContext.bound_account_id`, the binding chats and change runs already
use: credentials, providers and kubeconfigs refuse any other account), `get_managed_resources` lists only the bound
account's rows and says when the list was cut, and an issue opened in a bound run states its account.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.run_context import get_run_context, run_context
from tests.test_viewer_role import _temp_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "n32.db")
    for key, value in (("signal_gate_enabled", True), ("signal_gate_llm_enabled", False),
                       ("issue_exclude_patterns", [])):
        monkeypatch.setattr(settings, key, value)
    from agenticops.models import CloudAccount, get_session
    s = get_session()
    s.add(CloudAccount(id=1, name="cn", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"}))
    s.add(CloudAccount(id=2, name="global", provider="aws", is_enabled=True, credentials={"account_id": "222222222222"}))
    s.commit()
    yield s
    s.close()


def _resources(db, account_id, prefix, types):
    from agenticops.models import CloudResource
    n = 0
    for rtype, count in types:
        for _ in range(count):
            n += 1
            db.add(CloudResource(account_id=account_id, provider="aws", region="eu-west-1", resource_type=rtype,
                                 resource_id=f"{prefix}-{n}", name=f"{prefix}-{n}", managed=True, tags={}, raw_data={}))
    db.commit()


def _listed(text):
    import json
    return sorted(row["resource_id"] for row in json.loads(text.split("\n[")[0]))


# ── get_managed_resources ────────────────────────────────────────────────────

def test_a_bound_run_lists_only_its_own_accounts_resources(db):
    """A detection worker or a chat bound to an account — the same binding."""
    from agenticops.tools.metadata_tools import get_managed_resources
    _resources(db, 1, "cn", [("EC2", 3)])
    _resources(db, 2, "gl", [("EC2", 3)])
    with run_context(bound_account_id=2):
        assert _listed(get_managed_resources()) == ["gl-1", "gl-2", "gl-3"]
    with run_context(bound_account_id=1):
        assert _listed(get_managed_resources(resource_type="EC2")) == ["cn-1", "cn-2", "cn-3"]
    # unbound (Main in an unbound chat, the reporter): every enabled account, as before
    assert _listed(get_managed_resources()) == ["cn-1", "cn-2", "cn-3", "gl-1", "gl-2", "gl-3"]


def test_a_cut_list_says_how_many_rows_there_are_and_of_which_types(db):
    """Cut by whole rows, so what is shown is valid JSON and the note says how many it holds (an unbound list is
    still cut by characters, mid-row — 50 rows of JSON are longer than the list limit)."""
    from agenticops.tools.metadata_tools import get_managed_resources
    _resources(db, 1, "cn", [("EC2", 60)])                       # the other account's rows are not counted
    _resources(db, 2, "gl", [("EC2", 40), ("Lambda", 13)])
    with run_context(bound_account_id=2):
        out = get_managed_resources()
    shown, note = _listed(out), out.rsplit("\n", 1)[1]
    assert 0 < len(shown) <= 50 and all(r.startswith("gl-") for r in shown)
    assert f"showing {len(shown)} of 53" in note and "EC2 40" in note and "Lambda 13" in note
    assert "resource_type" in note and "truncated" not in out
    from agenticops.tools.metadata_tools import MAX_LIST_RESULT_CHARS
    assert len(out.rsplit("\n", 1)[0]) <= MAX_LIST_RESULT_CHARS          # within the list limit


def test_a_list_that_fits_has_no_note(db):
    from agenticops.tools.metadata_tools import get_managed_resources
    _resources(db, 2, "gl", [("EC2", 20)])
    with run_context(bound_account_id=2):
        out = get_managed_resources()
    assert "\n[" not in out and len(_listed(out)) == 20


def test_an_unbound_cut_list_says_how_many_too(db):
    """Unbound, it was cut mid-JSON and said nothing about the rest; since «之后» 13 it is the same whole-row list."""
    from agenticops.tools.metadata_tools import get_managed_resources
    _resources(db, 2, "gl", [("EC2", 53)])
    out = get_managed_resources()
    shown = _listed(out)
    assert f"[showing {len(shown)} of 53 managed resources — by type: EC2 53;" in out
    assert "of this account" not in out and "output truncated" not in out


# ── create_health_issue ──────────────────────────────────────────────────────

def _open(**kw):
    from agenticops.tools.metadata_tools import create_health_issue
    args = dict(resource_id="root", severity="medium", source="identity_hygiene",
                title="Root account MFA not enabled", description="AccountMFAEnabled=0", issue_type="iam_risk")
    args.update(kw)
    with patch("agenticops.services.rca_service.trigger_auto_rca"), \
            patch("agenticops.services.notification_service.notify_issue_created"):
        return create_health_issue(**args)


def _issue(db, text):
    from agenticops.models import HealthIssue
    db.expire_all()
    return db.get(HealthIssue, int(text.split("#")[1].split(":")[0].split()[0]))


def test_an_issue_opened_in_a_bound_run_is_of_that_account(db):
    with run_context(bound_account_id=2):
        out = _open()
    assert out.startswith("Created HealthIssue #")
    assert _issue(db, out).account_id == 2                        # «root» is in no inventory: the binding says whose


def test_an_unbound_issue_about_something_no_inventory_holds_still_has_no_account(db):
    out = _open()
    assert out.startswith("Created HealthIssue #") and _issue(db, out).account_id is None


def test_the_same_finding_in_two_accounts_is_two_issues(db):
    with run_context(bound_account_id=1):
        first = _open()
    with run_context(bound_account_id=2):
        second = _open()
    a, b = _issue(db, first), _issue(db, second)
    assert a.id != b.id and (a.account_id, b.account_id) == (1, 2)
    # control: unbound, the second call merges into the first (one identity without an account)
    third, fourth = _open(resource_id="sa-x", title="Stale key on sa-x"), _open(resource_id="sa-x", title="Stale key on sa-x")
    assert third.startswith("Created") and not fourth.startswith("Created")


def test_an_issue_about_a_resource_of_the_bound_account_anchors_there(db):
    _resources(db, 1, "same", [("EC2", 1)])
    _resources(db, 2, "same", [("EC2", 1)])                       # the same resource id in both accounts
    with run_context(bound_account_id=2):
        out = _open(resource_id="same-1", title="CPU high on same-1", issue_type="cpu_spike")
    issue = _issue(db, out)
    assert issue.account_id == 2 and issue.anchor_status == "anchored"


# ── the parallel checker ─────────────────────────────────────────────────────

def _two_accounts():
    accounts = [SimpleNamespace(id=1, name="cn", provider="aws", regions=["eu-west-1"]),
                SimpleNamespace(id=2, name="global", provider="aws", regions=["eu-west-1"])]
    provider = MagicMock()
    provider.sdk_session.return_value = MagicMock()
    return accounts, (lambda acct: (provider, MagicMock(name=f"cli-{acct.name}")))


def _run_checker(invoke):
    from agenticops.checker import check_accounts_parallel
    accounts, pair = _two_accounts()
    with patch("agenticops.scanner.engine._load_accounts", return_value=accounts), \
            patch("agenticops.scanner.engine._get_provider_and_tool", side_effect=pair), \
            patch("agenticops.agents.detect_agent._build_detect_agent_for_account", return_value=MagicMock()), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke):
        return asyncio.run(check_accounts_parallel(account_ids=[1, 2]))


def test_each_worker_is_bound_to_its_own_account():
    seen = []

    def invoke(agent, prompt, **kw):
        ctx = get_run_context()
        seen.append((prompt.split("'")[1], ctx.bound_account_id, ctx.read_only_run))
        return "Created 0 issues"

    result = _run_checker(invoke)
    assert sorted(seen) == [("cn", 1, "detect"), ("global", 2, "detect")]
    assert not any(a.errors for a in result.accounts)
    assert get_run_context().bound_account_id is None


def test_a_worker_cannot_reach_another_accounts_credentials():
    from agenticops.credentials.resolver import AccountResolutionError
    from agenticops.providers.base import get_provider
    refused = {}

    def invoke(agent, prompt, **kw):
        mine = get_run_context().bound_account_id
        other = SimpleNamespace(id=3 - mine, name="other", provider="aws")
        try:
            get_provider(other)
        except AccountResolutionError as e:
            refused[mine] = str(e)
        return "Created 0 issues"

    _run_checker(invoke)
    assert set(refused) == {1, 2} and all("bound to account" in m for m in refused.values())
