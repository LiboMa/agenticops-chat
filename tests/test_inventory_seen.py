"""Writers W1 and W3 only mark rows seen (MVP-2.6.1 Plan B Task 9): a row they see again returns
(absent_since cleared, scanned_at set). Neither ever marks a row absent; W2 (scanner/engine) owns that."""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import Base, CloudAccount, CloudResource, get_session

ACCT = 1
T0 = datetime(2026, 9, 1, 12, 0)
ARN = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/web/50dc6c495c0c9188"


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/seen.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(id=ACCT, name="global", provider="aws", is_enabled=True, credentials={}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _row(s, rid, rtype="EC2", absent_since=None, scanned_at=T0):
    r = CloudResource(account_id=ACCT, provider="aws", region="us-east-1", resource_type=rtype, resource_id=rid,
                      name=rid, tags={}, raw_data={}, status="running", scanned_at=scanned_at,
                      absent_since=absent_since)
    s.add(r)
    s.commit()
    return r.id


def _get(s, pk):
    s.expire_all()
    return s.get(CloudResource, pk)


def _w3():
    from agenticops.scan.scanner import AWSScanner

    account = SimpleNamespace(id=ACCT, provider="aws", credentials={}, regions=[], labels={}, last_scanned_at=None)
    with patch("agenticops.providers.get_provider", return_value=MagicMock()):
        return AWSScanner(account)


def _result(resources, error=None):
    from agenticops.scan.scanner import ScanResult

    return ScanResult(account_id="", region="us-east-1", service="ec2", resources=resources, error=error)


def test_w1_revives_an_absent_row_and_keeps_its_summary_string(db):
    from agenticops.tools.metadata_tools import save_resources

    pk = _row(db, "i-1", absent_since=T0)
    out = save_resources(json.dumps([{"resource_id": "i-1", "resource_type": "EC2", "region": "us-east-1",
                                      "name": "i-1"}]), account_id=ACCT)
    # scanner/engine._save_resources parses this string: it must stay byte-identical.
    assert out == "Saved 0 new resources, updated 1 existing (account=global, provider=aws)."
    row = _get(db, pk)
    assert row.absent_since is None and row.scanned_at != T0


def test_w3_revives_an_absent_row_and_sets_scanned_at(db):
    short = _row(db, "i-1", absent_since=T0, scanned_at=None)
    rekeyed = _row(db, "web", rtype="ELB", absent_since=T0, scanned_at=None)
    _w3().save_results([_result([
        {"resource_id": "i-1", "resource_type": "EC2", "resource_name": "i-1", "status": "running"},
        # the fallback path: an ARN-keyed resource found by its short id and re-keyed to the ARN
        {"resource_id": "web", "resource_arn": ARN, "resource_type": "ELB", "resource_name": "web",
         "status": "active"},
    ])])
    for pk in (short, rekeyed):
        row = _get(db, pk)
        assert row.absent_since is None and row.scanned_at is not None
    assert _get(db, rekeyed).resource_id == ARN


def test_w3_sets_scanned_at_on_a_new_row(db):
    saved = _w3().save_results([_result([
        {"resource_id": "i-new", "resource_type": "EC2", "resource_name": "i-new", "status": "running"}])])
    assert saved == 1
    row = db.query(CloudResource).filter_by(resource_id="i-new").one()
    assert row.scanned_at is not None and row.absent_since is None


def test_w3_never_marks_a_row_absent(db):
    unseen = _row(db, "i-gone")
    _w3().save_results([
        _result([{"resource_id": "i-1", "resource_type": "EC2", "resource_name": "i-1", "status": "running"}]),
        _result([], error="AWS Error (AccessDenied): denied"),
    ])
    assert _get(db, unseen).absent_since is None
    assert db.query(CloudResource).filter(CloudResource.absent_since.isnot(None)).count() == 0
