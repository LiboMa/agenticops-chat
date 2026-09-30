"""scripts/measure_graph_facts.py (MVP-2.6.1 spec §8.1, §8.2): it measures a copy and never writes the source."""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

import agenticops.models as models_mod
from agenticops.config import settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_graph_facts.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_graph_facts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A current-schema DB whose issues have never been through the resolver (anchor_status NULL)."""
    from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, get_session

    db = tmp_path / "source.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    monkeypatch.setattr(models_mod, "_engine", None)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    a = CloudAccount(name="acct-a", provider="aws", is_enabled=True, credentials={})
    b = CloudAccount(name="acct-b", provider="aws", is_enabled=True, credentials={})
    s.add_all([a, b])
    s.flush()
    for acct, rtype, rid, raw in [
        (a, "VPC", "vpc-a", {}),
        (a, "Subnet", "subnet-a", {"VpcId": "vpc-a"}),
        (a, "SecurityGroup", "sg-1", {"VpcId": "vpc-a"}),
        (a, "EC2", "i-1", {"NetworkInterfaces": [{"SubnetId": "subnet-a", "Groups": [{"GroupId": "sg-1"}]}]}),
        (a, "IAMRole", "shared-role", {}),
        (b, "IAMRole", "shared-role", {}),
    ]:
        s.add(CloudResource(account_id=acct.id, provider="aws", region="us-east-1", resource_type=rtype,
                            resource_id=rid, name=rid, tags={}, raw_data=raw))
    for rid, acct, status in [
        ("i-1", a, "open"),                               # anchored
        ("CIS-1.4", a, "open"),                           # account_level
        ("i-missing", a, "open"),                         # unanchored, rule none
        ("arn:aws:iam::999999999999:role/x", None, "open"),  # unanchored, rule unknown_account
        ("shared-role", None, "open"),                    # ambiguous: both accounts hold it, none named
        ("i-1", a, "resolved"),                           # closed: not counted
    ]:
        s.add(HealthIssue(resource_id=rid, account_id=acct.id if acct else None, severity="high", status=status,
                          source="test", title="t", description="d"))
    s.commit()
    s.close()
    models_mod._engine.dispose()
    monkeypatch.setattr(models_mod, "_engine", None)
    return db


def test_measures_a_copy_and_never_writes_the_source(source):
    before = _sha(source)
    report = _script().measure(source, runs=2)

    assert _sha(source) == before
    conn = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM health_issues WHERE anchor_status IS NOT NULL").fetchone() == (0,)
    conn.close()
    assert settings.database_url == f"sqlite:///{source}"   # restored
    assert models_mod._engine is None

    a = report["anchoring"]
    assert (a["total"], a["anchored"], a["account_level"], a["ambiguous"], a["unanchored"]) == (5, 1, 1, 1, 2)
    assert (a["rate"], a["met"]) == (0.4, False)
    assert {(x["status"], x["rule"], x["count"]) for x in a["reasons"]} == {
        ("ambiguous", "resource_id", 1), ("unanchored", "none", 1), ("unanchored", "unknown_account", 1)}

    d = report["duplicates"]
    assert (d["groups"], d["open_issues"], d["crossed"], d["guessed"]) == (1, 1, 0, 0)
    assert (d["probe_guessed"], d["in_account_probes"], d["in_account_anchored"], d["probe_crossed"]) == (0, 2, 2, 0)
    assert d["met"] is True

    assert report["graph"]["relations"].get("llm", 0) == 0
    assert report["graph"]["relations"]["rule"] >= 3

    q = report["queries"]
    assert (q["refs"], q["calls"]) == (1, 2)
    assert q["max_sql"] <= 5
    assert q["max_nodes"] >= 3


def test_cli_prints_json_and_writes_the_doc(source, tmp_path, capsys):
    doc = tmp_path / "report.md"
    assert _script().main(["--db", str(source), "--runs", "1", "--doc", str(doc)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["anchoring"]["total"] == 5
    text = doc.read_text(encoding="utf-8")
    assert "**40.0%**" in text and "**未达标**" in text
    assert "不放宽规则去凑数" in text
    assert "| unanchored | unknown_account | 1 |" in text


def test_missing_source_fails_and_creates_nothing(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        _script().measure(missing)
    assert not missing.exists()
