"""What the reporter reads is counted by the code («之后» 13, 2026-11-26).

A real daily report (N21) had 21 truncated tool results and 10 «too long, head kept»: the inventory tool gave at most
50 rows, cut mid-JSON at 6,000 characters without saying how many were left, and the prompt asked the model to
count «resources by type and region» itself; no tool read the security score. Now `get_inventory_summary` counts
per account by type and region in SQL, `get_security_summary` reads each account's newest snapshot, the two list
tools hand over whole rows and say «showing N of TOTAL», and a run bound to one account reads only that account —
`list_health_issues` included (it listed every account's issues)."""
import json
from datetime import datetime, timezone

from agenticops.models import CloudResource, HealthIssue, SecuritySnapshot
from agenticops.run_context import run_context
from agenticops.services import report_coverage as rc
from tests.test_report_coverage import NOW, _issue, _resource, db  # noqa: F401  (the fixture)


def _listed(out: str) -> list:
    """The JSON rows of a list tool's answer (a «showing N of TOTAL» line may follow them)."""
    return json.loads(out.split("\n[showing ")[0])


def _inventory(db):
    for n in range(3):
        _resource(db, n)                                                  # prod, us-east-1, EC2
    _resource(db, 3, region="eu-west-1", rtype="RDS")
    _resource(db, 4, account=2, region="ap-southeast-1", rtype="Lambda")
    _resource(db, 5, account=3, region="us-west-2")                       # a disabled account: not counted
    db.add(CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EC2", resource_id="i-gone",
                         name="gone", tags={}, raw_data={}, managed=True,
                         absent_since=datetime(2026, 11, 1, tzinfo=timezone.utc)))  # absent: not counted
    db.add(CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EC2", resource_id="i-free",
                         name="free", tags={}, raw_data={}, managed=False))          # unmanaged: not counted
    db.commit()


# ── get_inventory_summary ────────────────────────────────────────────────────

def test_the_summary_counts_what_the_inventory_holds(db):
    from agenticops.tools.metadata_tools import get_inventory_summary
    _inventory(db)
    with run_context(coverage=rc.begin(NOW)):
        got = json.loads(get_inventory_summary())
        scope = rc.current().as_dict()
    assert got == {"total": 5, "accounts": [
        {"account": "lab", "total": 1, "by_type": {"Lambda": 1}, "by_region": {"ap-southeast-1": 1}},
        {"account": "prod", "total": 4, "by_type": {"EC2": 3, "RDS": 1}, "by_region": {"eu-west-1": 1, "us-east-1": 3}}]}
    assert (scope["accounts"], scope["regions"]) == (["lab", "prod"], ["ap-southeast-1", "eu-west-1", "us-east-1"])
    assert scope["completeness"] == "complete"


def test_the_summary_of_one_account_and_of_a_bound_run(db):
    from agenticops.tools.metadata_tools import get_inventory_summary
    _inventory(db)
    assert [a["account"] for a in json.loads(get_inventory_summary(account="lab"))["accounts"]] == ["lab"]
    with run_context(bound_account_id=1):
        assert [a["account"] for a in json.loads(get_inventory_summary())["accounts"]] == ["prod"]
        refused = get_inventory_summary(account="lab")
    assert refused.startswith("Error:") and "prod" in refused
    assert get_inventory_summary(account="nobody").startswith("Error:")


# ── get_security_summary ─────────────────────────────────────────────────────

def test_the_security_summary_reads_each_accounts_newest_snapshot(db):
    from agenticops.tools.metadata_tools import get_security_summary
    db.add_all([SecuritySnapshot(account_id="prod", overall_score=40.0, category_scores={"iam": 30.0},
                                 created_at=datetime(2026, 11, 20, tzinfo=timezone.utc)),
                SecuritySnapshot(account_id="prod", overall_score=72.5, category_scores={"iam": 60.0, "network": None},
                                 created_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                                 collection_health={"status": "partial",
                                                    "sources": {"iam": {"ok": True}, "network": {"ok": False,
                                                                                                 "error": "x"}}}),
                SecuritySnapshot(account_id="lab", overall_score=None, category_scores={},
                                 created_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                                 collection_health={"status": "failed", "sources": {"iam": {"ok": False}}})])
    _issue(db, 1, detected_by="security_posture", account_id=1)
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        got = json.loads(get_security_summary())
        assert rc.current().as_dict()["accounts"] == ["lab", "prod"]
    by = {a["account"]: a for a in got["accounts"]}
    assert by["prod"]["score"] == 72.5 and by["prod"]["category_scores"] == {"iam": 60.0, "network": None}
    assert by["prod"]["collection"] == "partial" and by["prod"]["sources_not_read"] == ["network"]
    assert by["prod"]["open_findings"] == 1 and by["prod"]["snapshot_at"].startswith("2026-11-25")
    assert by["lab"]["score"] is None and by["lab"]["collection"] == "failed"
    assert "nothing could be read" in by["lab"]["note"]
    with run_context(bound_account_id=2):
        assert [a["account"] for a in json.loads(get_security_summary())["accounts"]] == ["lab"]
        assert get_security_summary(account="prod").startswith("Error:")


def test_no_snapshot_is_said_so(db):
    from agenticops.tools.metadata_tools import get_security_summary
    assert "no security snapshot" in get_security_summary(account="lab").lower()


# ── the two list tools: whole rows, and how many were left ───────────────────

def test_a_cut_inventory_list_is_whole_rows_and_says_how_many_are_left(db, monkeypatch):
    from agenticops.tools import metadata_tools
    from agenticops.tools.metadata_tools import get_managed_resources
    for n in range(60):
        _resource(db, n, rtype="EC2" if n < 45 else "RDS")
    db.commit()
    with run_context(coverage=rc.begin(NOW)):
        out = get_managed_resources()
        assert rc.current().as_dict()["partial"]["truncated"] == 1               # one cut result, counted once
    rows = _listed(out)                                                          # whole rows: it parses
    assert 0 < len(rows) <= 50
    assert f"[showing {len(rows)} of 60 managed resources — by type: EC2 45, RDS 15;" in out
    monkeypatch.setattr(metadata_tools, "MAX_LIST_RESULT_CHARS", 10**6)
    assert f"[showing 50 of 60 managed resources" in get_managed_resources()     # the 50-row cap says it too


def test_a_cut_issue_list_is_whole_rows_and_says_how_many_are_left(db):
    from agenticops.tools.metadata_tools import list_health_issues
    for n in range(5):
        _issue(db, n)
    db.commit()
    out = list_health_issues(limit=2)
    assert len(_listed(out)) == 2 and "[showing 2 of 5 issues" in out
    assert "\n[" not in list_health_issues(limit=5)


def test_a_bound_run_lists_only_its_accounts_issues(db):
    from agenticops.tools.metadata_tools import list_health_issues
    _issue(db, 1, account_id=1)
    _issue(db, 2, account_id=2)
    _issue(db, 3)                                                                # no account
    db.commit()
    assert len(_listed(list_health_issues())) == 3
    with run_context(bound_account_id=2, coverage=rc.begin(NOW)):
        assert [i["resource_id"] for i in _listed(list_health_issues())] == ["i-0002"]
        assert rc.current().as_dict()["accounts"] == ["lab"]                     # the scope it read


# ── the reporter is given them ───────────────────────────────────────────────

def test_the_reporter_reads_counts_and_the_score_with_the_new_tools():
    import importlib
    mod = importlib.import_module("agenticops.agents.reporter_agent")   # the package re-exports the tool by this name
    src = open(mod.__file__).read()
    assert "get_inventory_summary," in src and "get_security_summary," in src
    prompt = mod.REPORTER_SYSTEM_PROMPT
    assert "get_inventory_summary" in prompt and "get_security_summary" in prompt
    assert "generate_report tool" not in prompt                                  # there is no such tool
