"""Relation registry: fault-propagation direction per relation type (MVP-2.6.1, spec §3.A.2).

Pure data + functions. Edges are always written src → dst as named here; the propagation value says
which way a fault travels along that edge:

  FORWARD  — src → dst  (contains: parent → child; attached_to; restricts)
  REVERSE  — dst → src  (secured_by: sg → instance; routes_to: target → router; uses; runs_on)
  BOTH     — manages, same_as
  NONE     — LLM-only display types (references, inferred_group) and anything unregistered

upstream(x) = resources x depends on (a fault there reaches x) → root-cause candidates.
downstream(x) = resources that depend on x → blast radius.
"""
from typing import Iterable, Optional

FORWARD = "forward"
REVERSE = "reverse"
BOTH = "both"
NONE = "none"

PROPAGATION: dict[str, str] = {
    "contains": FORWARD,
    "secured_by": REVERSE,
    "attached_to": FORWARD,
    "routes_to": REVERSE,
    "manages": BOTH,
    "uses": REVERSE,
    "restricts": FORWARD,
    "runs_on": REVERSE,
    "same_as": BOTH,
    "references": NONE,
    "inferred_group": NONE,
}

# Types the rule layer may emit and that take part in propagation.
RULE_RELATION_TYPES: frozenset[str] = frozenset(t for t, p in PROPAGATION.items() if p != NONE)

# restricts / uses reach the K8s causes of a workload's fault: its NetworkPolicy / PDB, its ConfigMap / Secret / PVC.
_NETWORK = ("contains", "secured_by", "routes_to", "restricts", "uses")
DEFAULT_RELATIONS_BY_CLASS: dict[str, tuple[str, ...]] = {
    "network": _NETWORK,
    "compute": _NETWORK + ("attached_to", "manages", "runs_on", "same_as"),
    "database": ("contains", "secured_by", "uses"),
    "other": tuple(sorted(RULE_RELATION_TYPES)),
}

ISSUE_TYPE_CLASS: dict[str, str] = {
    "network_flap": "network",
    "connectivity": "network",
    "security_exposure": "network",
    "cpu_spike": "compute",
    "memory_pressure": "compute",
    "disk_full": "compute",
    "availability": "compute",
    "capacity_risk": "compute",
    "performance_degradation": "compute",
    "spof": "compute",
}

_DATABASE_TYPES = frozenset({"RDS", "DynamoDB", "OpenSearch"})


def propagation(relation_type: str) -> str:
    return PROPAGATION.get(relation_type, NONE)


def issue_class(issue_type: Optional[str], anchor_type: Optional[str] = None) -> str:
    """A database anchor wins over the issue type: its dependencies are subnets, groups and keys."""
    if anchor_type in _DATABASE_TYPES:
        return "database"
    return ISSUE_TYPE_CLASS.get(issue_type or "", "other")


def default_relations(issue_type: Optional[str], anchor_type: Optional[str] = None) -> tuple[str, ...]:
    return DEFAULT_RELATIONS_BY_CLASS[issue_class(issue_type, anchor_type)]


def step(relation_type: str, frontier_is_src: bool) -> tuple[bool, bool]:
    """Walking an edge from the frontier end: is the OTHER end (downstream, upstream) of the frontier?"""
    p = propagation(relation_type)
    if p == BOTH:
        return True, True
    if p == FORWARD:  # fault src → dst: dst is downstream of src, src is upstream of dst
        return (True, False) if frontier_is_src else (False, True)
    if p == REVERSE:  # fault dst → src
        return (False, True) if frontier_is_src else (True, False)
    return False, False


def _neighbors(node, edges: Iterable[tuple], want_upstream: bool) -> set:
    out = set()
    for src, dst, rtype in edges:
        if src == node:
            other, is_src = dst, True
        elif dst == node:
            other, is_src = src, False
        else:
            continue
        down, up = step(rtype, frontier_is_src=is_src)
        if (up if want_upstream else down):
            out.add(other)
    return out


def upstream_of(node, edges: Iterable[tuple]) -> set:
    return _neighbors(node, edges, want_upstream=True)


def downstream_of(node, edges: Iterable[tuple]) -> set:
    return _neighbors(node, edges, want_upstream=False)
