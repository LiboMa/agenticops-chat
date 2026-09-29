"""L1 deterministic edge derivation. Pure function: resource rows -> nodes + edges.

Every edge produced here is provenance=rule with confidence 1.0 — the graph's
factual skeleton, which the LLM layer is never allowed to override.
"""

import re
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

# Vocabulary the LLM enrichment prompt may use (unchanged since MVP-2.3). Propagation semantics for rule
# relations live in agenticops.graph.relations — this set only gates what an LLM edge may be called.
LLM_RELATION_TYPES = frozenset({
    "contains", "references", "member_of", "attached_to",
    "secured_by", "routes_to", "inferred_group",
})

# Tag key -> group kind. Order matters only for display; all matched tags group.
TAG_GROUP_KEYS = {
    "Project": "project", "Environment": "environment", "Env": "environment",
    "System": "system", "Stack": "stack",
}


def resource_node_id(pk: int) -> str:
    return f"res:{pk}"


def group_node_id(slug: str) -> str:
    return f"grp:{slug}"


def account_node_id(account_id: int) -> str:
    return f"acct:{account_id}"


def group_slug(account_id: int, kind: str, value: str) -> str:
    return f"{account_id}:{kind}:{value}"


# ── Identity helpers (MVP-2.6.1): shared by the anchoring resolver, the K8s connector and the rules ──

_ARN_REGION = re.compile(r"^arn:aws[a-z-]*:[^:]*:(?P<region>[^:]*):")

# K8s Kind → resource_type (spec §3.B.3). Plan B's connector writes these; resolver and rules read them.
K8S_KIND_TYPES = {
    "Namespace": "K8s_Namespace", "Deployment": "K8s_Deployment", "StatefulSet": "K8s_StatefulSet",
    "DaemonSet": "K8s_DaemonSet", "Service": "K8s_Service", "Ingress": "K8s_Ingress", "Node": "K8s_Node",
    "ConfigMap": "K8s_ConfigMap", "Secret": "K8s_Secret", "PersistentVolumeClaim": "K8s_PVC",
    "PodDisruptionBudget": "K8s_PDB", "NetworkPolicy": "K8s_NetworkPolicy", "Pod": "K8s_Pod",
}


def k8s_resource_id(cluster: str, kind: str, name: str, namespace: Optional[str] = None) -> str:
    """'<cluster>/<Kind>/<ns>/<name>' for namespaced objects, '<cluster>/<Kind>/<name>' for cluster-scoped ones."""
    return f"{cluster}/{kind}/{namespace}/{name}" if namespace else f"{cluster}/{kind}/{name}"


def arn_region(value: str) -> str:
    """Region segment of an ARN; '' for global services and for anything that is not an ARN."""
    m = _ARN_REGION.match(value or "")
    return m.group("region") if m else ""


def short_id(value: str) -> str:
    """An ARN's resource part down to its last path segment ('…:instance/i-1' → 'i-1', '…:db:mydb' → 'mydb').
    Anything that is not an ARN is returned unchanged — a K8s id's last segment is not an identity."""
    v = (value or "").strip()
    if v.startswith("arn:"):
        parts = v.split(":", 5)
        if len(parts) == 6:
            res = parts[5]
            if "/" in res:
                return res.rsplit("/", 1)[1]
            return res.split(":", 1)[1] if ":" in res else res
    return v


def type_family(resource_type: str, families: dict) -> str:
    """The family name when identity_type_families lists the type, else the type itself."""
    for family, members in (families or {}).items():
        if resource_type in (members or ()):
            return family
    return resource_type


def physical_key(row: dict, families: dict) -> tuple:
    """Rows with the same key are one physical resource: account, region (from the ARN when the column is
    empty), short id and type family."""
    rid = row.get("resource_id") or ""
    return (row.get("account_id"), row.get("region") or arn_region(rid), short_id(rid),
            type_family(row.get("resource_type") or "", families))


def _scan_ts(value) -> datetime:
    if not isinstance(value, datetime):
        return datetime.min
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def dedup_physical(rows: list, families: dict) -> tuple[list, list]:
    """Collapse rows that are one physical resource. The newest scanned_at wins, then the higher id.
    Returns (canonical rows sorted by id, [(duplicate, canonical), …] sorted by duplicate id)."""
    groups: dict = {}
    for row in rows:
        groups.setdefault(physical_key(row, families), []).append(row)
    canon, dups = [], []
    for members in groups.values():
        members.sort(key=lambda r: (_scan_ts(r.get("scanned_at")), r["id"]), reverse=True)
        canon.append(members[0])
        dups.extend((m, members[0]) for m in members[1:])
    canon.sort(key=lambda r: r["id"])
    dups.sort(key=lambda pair: pair[0]["id"])
    return canon, dups


def _iter_values(obj: Any, key: str) -> Iterator[str]:
    """Yield every string value stored under `key` anywhere in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                yield v
            else:
                yield from _iter_values(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_values(item, key)


def _rule_edge(source: str, target: str, relation_type: str, evidence: str) -> dict:
    return {
        "source": source, "target": target, "relation_type": relation_type,
        "provenance": "rule", "evidence": evidence, "confidence": 1.0,
        "model_id": None, "prompt_version": None,
    }


def _node(resource: dict) -> dict:
    return {
        "id": resource_node_id(resource["id"]), "kind": "resource",
        "resource_type": resource.get("resource_type", ""),
        "name": resource.get("name") or resource.get("resource_id", ""),
        "account_id": resource.get("account_id"),
        "region": resource.get("region", ""),
        "provider": resource.get("provider", ""),
        "resource_id": resource.get("resource_id", ""),
    }


_SUBNET = ("Subnet",)
_VPC = ("VPC",)
_SG = ("SecurityGroup",)
_EC2 = ("EC2",)
_ELB = ("ELB",)
_ROLE = ("IAMRole",)
_KMS = ("KMS",)
# raw_data keys holding a row's own ARN when resource_id is a short name (IAMRole.Arn, KMS.KeyArn)
_OWN_ARN_KEYS = ("Arn", "KeyArn")


def _dicts(value) -> list:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _strs(value) -> list:
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _ref_index(resources: list) -> dict:
    """(account_id, resource_id or own ARN) -> [(pk, resource_type)]. References resolve inside one account."""
    index: dict = {}
    for r in resources:
        raw = r.get("raw_data") if isinstance(r.get("raw_data"), dict) else {}
        keys = {r["resource_id"]} | {raw[k] for k in _OWN_ARN_KEYS if isinstance(raw.get(k), str) and raw[k]}
        for key in keys:
            index.setdefault((r["account_id"], key), []).append((r["id"], r.get("resource_type", "")))
    return index


def _ref(index: dict, account_id, value, types=None) -> Optional[str]:
    """Node id of the one row in account_id that `value` names (optionally of `types`); None if 0 or ≥ 2."""
    hits = [pk for pk, rtype in index.get((account_id, value), ()) if types is None or rtype in types]
    return resource_node_id(hits[0]) if len(hits) == 1 else None


def _spanned_subnets(rtype: str, raw: dict) -> list:
    """(subnet id, evidence path) for types whose raw_data lists every subnet they span."""
    if rtype == "RDS":
        group = raw.get("DBSubnetGroup") if isinstance(raw.get("DBSubnetGroup"), dict) else {}
        return [(s["SubnetIdentifier"], "raw_data.DBSubnetGroup.Subnets[].SubnetIdentifier")
                for s in _dicts(group.get("Subnets")) if isinstance(s.get("SubnetIdentifier"), str)]
    if rtype == "ELB":
        return [(z["SubnetId"], "raw_data.AvailabilityZones[].SubnetId")
                for z in _dicts(raw.get("AvailabilityZones")) if isinstance(z.get("SubnetId"), str)]
    return []


def _aws_relations(rtype: str, raw: dict, self_node: str, ref) -> Iterator[tuple]:
    """Type-specific AWS relations (spec §3.A.3 ②) as (src, dst, relation_type, evidence), written the
    graph.relations way round. `ref(value, types)` resolves inside the row's account. A missing field or an
    unresolvable reference yields a None end, which the caller drops."""
    if rtype == "AutoScaling":
        for inst in _dicts(raw.get("Instances")):
            iid = inst.get("InstanceId")
            if isinstance(iid, str):
                yield self_node, ref(iid, _EC2), "manages", f"raw_data.Instances[].InstanceId={iid}"
        # Classic load balancers only; ALB/NLB attach through target groups, which are not collected.
        for name in _strs(raw.get("LoadBalancerNames")):
            yield ref(name, _ELB), self_node, "routes_to", f"raw_data.LoadBalancerNames={name}"
    elif rtype == "RDS":
        for group in _dicts(raw.get("VpcSecurityGroups")):
            gid = group.get("VpcSecurityGroupId")
            if isinstance(gid, str):
                yield self_node, ref(gid, _SG), "secured_by", f"raw_data.VpcSecurityGroups[].VpcSecurityGroupId={gid}"
    elif rtype == "ELB":
        for gid in _strs(raw.get("SecurityGroups")):
            yield self_node, ref(gid, _SG), "secured_by", f"raw_data.SecurityGroups={gid}"
    elif rtype == "Lambda":
        for key, types in (("Role", _ROLE), ("KMSKeyArn", _KMS)):
            arn = raw.get(key)
            if isinstance(arn, str) and arn:
                yield self_node, ref(arn, types), "uses", f"raw_data.{key}={arn}"


def derive_rule_graph(resources: list) -> dict:
    """Build the deterministic rule layer. Returns {nodes, edges, groups}.

    Id references resolve only inside the referring row's account: the same resource_id in two accounts is
    two resources (spec §3.A.3 ①). Each (source, target, relation_type) is emitted once, never as a self-loop."""
    index = _ref_index(resources)

    nodes: list = []
    edges: list = []
    seen: set = set()
    account_ids: set = set()
    groups: dict = {}  # slug -> {slug, display_name, kind, member_count}

    def add(source, target, relation_type, evidence):
        key = (source, target, relation_type)
        if source and target and source != target and key not in seen:
            seen.add(key)
            edges.append(_rule_edge(source, target, relation_type, evidence))

    for r in resources:
        self_node = resource_node_id(r["id"])
        nodes.append(_node(r))
        acct = r["account_id"]
        account_ids.add(acct)
        raw = r.get("raw_data") if isinstance(r.get("raw_data"), (dict, list)) else {}
        rid = r["resource_id"]
        rtype = r.get("resource_type", "")

        def ref(value, types=None, _acct=acct):
            return _ref(index, _acct, value, types)

        # --- Containment: every spanned subnet, else the nearest parent (subnet > vpc > account) ---
        spanned = [(ref(sid, _SUBNET), f"{path}={sid}")
                   for sid, path in (_spanned_subnets(rtype, raw) if isinstance(raw, dict) else [])]
        spanned = [(parent, ev) for parent, ev in spanned if parent]
        if spanned:
            for parent, ev in spanned:
                add(parent, self_node, "contains", ev)
        else:
            parent, parent_evidence = None, ""
            subnet = next((s for s in _iter_values(raw, "SubnetId") if s != rid), None)
            if rtype != "Subnet" and subnet and ref(subnet, _SUBNET):
                parent, parent_evidence = ref(subnet, _SUBNET), f"raw_data.SubnetId={subnet}"
            if parent is None:
                vpc = next((v for v in _iter_values(raw, "VpcId") if v != rid), None)
                if rtype != "VPC" and vpc and ref(vpc, _VPC):
                    parent, parent_evidence = ref(vpc, _VPC), f"raw_data.VpcId={vpc}"
            if parent is None:
                parent, parent_evidence = account_node_id(acct), "account membership"
            add(parent, self_node, "contains", parent_evidence)

        # --- Security groups guard compute ---
        for gid in sorted({g for g in _iter_values(raw, "GroupId") if g != rid}):
            add(self_node, ref(gid, _SG), "secured_by", f"raw_data.GroupId={gid}")

        # --- Type-specific AWS relations ---
        if isinstance(raw, dict):
            for source, target, relation_type, evidence in _aws_relations(rtype, raw, self_node, ref):
                add(source, target, relation_type, evidence)

        # --- Tag grouping: member_of ---
        tags = r.get("tags") if isinstance(r.get("tags"), dict) else {}
        for tag_key, kind in TAG_GROUP_KEYS.items():
            val = tags.get(tag_key)
            if isinstance(val, str) and val.strip():
                slug = group_slug(acct, kind, val.strip())
                gnode = group_node_id(slug)
                g = groups.setdefault(slug, {"slug": slug, "display_name": val.strip(),
                                             "kind": kind, "member_count": 0})
                g["member_count"] += 1
                add(self_node, gnode, "member_of", f"tags.{tag_key}={val.strip()}")

    # Account nodes.
    for aid in sorted(account_ids):
        nodes.append({"id": account_node_id(aid), "kind": "account", "account_id": aid,
                      "name": f"account:{aid}", "resource_type": "", "region": "", "provider": ""})
    # Group nodes.
    for slug, g in groups.items():
        nodes.append({"id": group_node_id(slug), "kind": "group", "name": g["display_name"],
                      "group_kind": g["kind"], "member_count": g["member_count"],
                      "resource_type": "", "region": "", "provider": "", "account_id": None})

    return {"nodes": nodes, "edges": edges, "groups": list(groups.values())}
