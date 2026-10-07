"""services.inventory (MVP-2.6.1): the one "present" definition and the two helpers every inventory writer
shares. mark_unseen_absent marks only unseen present rows inside the given account / provider / type (and
criteria), never deletes, and never moves an absent_since that is already set."""
from datetime import datetime

import pytest

from agenticops.models import Base, CloudAccount, CloudResource, get_session
from agenticops.services.inventory import PRESENT, mark_seen, mark_unseen_absent

ACCT, OTHER = 1, 2
T0 = datetime(2026, 9, 1, 12, 0)
T1 = datetime(2026, 9, 2, 12, 0)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/inventory.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=ACCT, name="global", provider="aws", is_enabled=True, credentials={}),
               CloudAccount(id=OTHER, name="cn", provider="aws", is_enabled=True, credentials={})])
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved_url


def _row(s, rid, rtype="EC2", account=ACCT, provider="aws", region="us-east-1", absent_since=None):
    r = CloudResource(account_id=account, provider=provider, region=region, resource_type=rtype, resource_id=rid,
                      name=rid, tags={}, raw_data={}, status="running", scanned_at=T0, absent_since=absent_since)
    s.add(r)
    s.commit()
    return r.id


def _absent(s, pk):
    s.expire_all()
    return s.get(CloudResource, pk).absent_since


def _mark(s, seen, **kw):
    args = dict(account_id=ACCT, provider="aws", resource_type="EC2", seen=set(seen), now=T1)
    args.update(kw)
    marked = mark_unseen_absent(s, **args)
    s.commit()
    return marked


def test_marks_only_unseen_present_rows(db):
    seen_pk, gone_pk = _row(db, "i-seen"), _row(db, "i-gone")
    assert _mark(db, {"i-seen"}) == 1
    assert (_absent(db, seen_pk), _absent(db, gone_pk)) == (None, T1)


def test_criteria_bounds_the_rows(db):
    east, west = _row(db, "i-east"), _row(db, "i-west", region="us-west-2")
    assert _mark(db, set(), criteria=(CloudResource.region == "us-east-1",)) == 1
    assert (_absent(db, east), _absent(db, west)) == (T1, None)


def test_never_touches_another_account_provider_or_type(db):
    other_account = _row(db, "i-x", account=OTHER)
    other_provider = _row(db, "i-y", provider="kubernetes")
    other_type = _row(db, "vol-z", rtype="EBS")
    assert _mark(db, set()) == 0
    assert [_absent(db, pk) for pk in (other_account, other_provider, other_type)] == [None, None, None]


def test_never_deletes(db):
    _row(db, "i-a")
    _row(db, "i-b")
    before = db.query(CloudResource).count()
    assert _mark(db, set()) == 2
    assert db.query(CloudResource).count() == before


def test_an_absent_row_keeps_its_original_absent_since(db):
    pk = _row(db, "i-old", absent_since=T0)
    assert _mark(db, set()) == 0
    assert _absent(db, pk) == T0


def test_mark_seen_revives_a_row_and_present_counts_it_again(db):
    pk = _row(db, "i-back", absent_since=T0)
    assert db.query(CloudResource).filter(PRESENT).count() == 0
    mark_seen(db.get(CloudResource, pk), T1)
    db.commit()
    db.expire_all()
    row = db.get(CloudResource, pk)
    assert (row.scanned_at, row.absent_since) == (T1, None)
    assert db.query(CloudResource).filter(PRESENT).count() == 1
