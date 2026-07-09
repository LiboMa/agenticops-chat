"""Content hashing: stable, volatile-field-insensitive, correct diff."""

from agenticops.galaxy.hashing import strip_volatile, canonical_json, content_hash, compute_diff


def _res(**kw):
    base = {"resource_type": "EC2", "resource_id": "i-1", "name": "web",
            "tags": {"Project": "demo"}, "raw_data": {"State": {"Name": "running"}}}
    base.update(kw)
    return base


def test_canonical_json_key_order_stable():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_strip_volatile_removes_timestamps_recursively():
    stripped = strip_volatile({"LaunchTime": "t", "nested": {"AttachTime": "t", "keep": 1}})
    assert "LaunchTime" not in stripped
    assert "AttachTime" not in stripped["nested"]
    assert stripped["nested"]["keep"] == 1


def test_hash_ignores_volatile_fields():
    a = _res(raw_data={"State": {"Name": "running"}, "LaunchTime": "2024-01-01"})
    b = _res(raw_data={"State": {"Name": "running"}, "LaunchTime": "2025-09-09"})
    assert content_hash(a) == content_hash(b)


def test_hash_changes_on_material_field():
    a = _res(raw_data={"State": {"Name": "running"}})
    b = _res(raw_data={"State": {"Name": "stopped"}})
    assert content_hash(a) != content_hash(b)


def test_compute_diff():
    prev = {1: "h1", 2: "h2", 3: "h3"}
    current = {1: "h1", 2: "CHANGED", 4: "h4"}
    d = compute_diff(prev, current)
    assert d.added == {4}
    assert d.changed == {2}
    assert d.removed == {3}
    assert d.dirty == {2, 4}
