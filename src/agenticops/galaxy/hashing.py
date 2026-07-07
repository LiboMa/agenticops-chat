"""Content-hash incremental build support. Pure functions, no DB."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# Fields that change without changing a resource's identity/relationships.
VOLATILE_KEYS = frozenset({
    "LaunchTime", "AttachTime", "CreateTime", "CreatedTime", "createDate",
    "LastModified", "lastModified", "updatedAt", "UpdateTime",
    "AvailableIpAddressCount", "ClientToken", "RequesterId",
})

_HASH_FIELDS = ("resource_type", "resource_id", "name", "tags", "raw_data")


def strip_volatile(obj: Any) -> Any:
    """Return a deep copy of obj with all VOLATILE_KEYS removed at every depth."""
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, non-ASCII preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(resource: dict) -> str:
    """sha256 over the stable subset of a resource, volatile fields stripped."""
    subset = {k: resource.get(k) for k in _HASH_FIELDS}
    return hashlib.sha256(canonical_json(strip_volatile(subset)).encode("utf-8")).hexdigest()


@dataclass
class Diff:
    added: set
    changed: set
    removed: set

    @property
    def dirty(self) -> set:
        return self.added | self.changed


def compute_diff(prev: dict, current: dict) -> Diff:
    """prev/current map resource_pk -> content_hash."""
    prev_keys, cur_keys = set(prev), set(current)
    added = cur_keys - prev_keys
    removed = prev_keys - cur_keys
    changed = {k for k in (cur_keys & prev_keys) if prev[k] != current[k]}
    return Diff(added=added, changed=changed, removed=removed)
