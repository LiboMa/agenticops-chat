"""K8s rule relations (MVP-2.6.1 spec §3.A.3 ③) over the K8S_RAW_DATA_CONTRACT shapes."""

from datetime import datetime

from agenticops.galaxy.rules import K8S_KIND_TYPES, derive_rule_graph, k8s_resource_id

FAMILIES = {"EKS": ["EKS", "EKS_Cluster"]}
CL = "shop-eks"
REGION = "us-east-1"


def _k(pk, kind, name, ns=None, account_id=1, **raw):
    body = {"cluster": CL, "namespace": ns, "labels": {}}
    body.update(raw)
    return {"id": pk, "account_id": account_id, "provider": "kubernetes", "region": REGION,
            "resource_type": K8S_KIND_TYPES[kind], "resource_id": k8s_resource_id(CL, kind, name, ns),
            "name": name, "tags": {}, "raw_data": body}


def _aws(pk, rtype, rid, raw=None, region=REGION, account_id=1, scanned_at=None):
    return {"id": pk, "account_id": account_id, "provider": "aws", "region": region, "resource_type": rtype,
            "resource_id": rid, "name": rid, "tags": {}, "raw_data": raw or {}, "scanned_at": scanned_at}


def _derive(rows):
    return derive_rule_graph(rows, families=FAMILIES)


def _edges(g, rtype=None):
    return {(e["source"], e["target"], e["relation_type"]) for e in g["edges"]
            if rtype is None or e["relation_type"] == rtype}


def test_cluster_contains_namespace_and_node_and_namespace_contains_its_objects():
    g = _derive([
        _aws(1, "EKS", CL, scanned_at=datetime(2026, 9, 1)),
        _aws(2, "EKS_Cluster", f"arn:aws:eks:{REGION}:111122223333:cluster/{CL}", scanned_at=datetime(2026, 9, 27)),
        _k(10, "Namespace", "shop"),
        _k(11, "Node", "ip-10-0-1-5"),
        _k(12, "Deployment", "checkout", "shop"),
    ])
    e = _edges(g, "contains")
    assert {("res:2", "res:10", "contains"), ("res:2", "res:11", "contains"), ("res:10", "res:12", "contains")} <= e
    assert ("res:2", "res:12", "contains") not in e      # the namespace is the nearer parent
    assert not [t for t in e if t[0] == "res:1"]          # the older duplicate cluster row holds nothing


def test_objects_fall_back_to_the_cluster_then_the_account():
    g = _derive([
        _aws(1, "EKS", CL),
        _k(12, "Deployment", "checkout", "ghost"),         # its Namespace was never collected
        _k(13, "Namespace", "shop", account_id=3),          # a kubernetes-provider account has no cluster row
    ])
    assert {("res:1", "res:12", "contains"), ("acct:3", "res:13", "contains")} <= _edges(g, "contains")


def test_cluster_lookup_is_per_region_and_needs_exactly_one_physical_cluster():
    rows = [_aws(1, "EKS", CL, region="us-east-1"), _aws(2, "EKS", CL, region="us-west-2"), _k(10, "Namespace", "shop")]
    e = _edges(_derive(rows), "contains")
    assert ("res:1", "res:10", "contains") in e
    assert not [t for t in e if t[0] == "res:2"]
    # Without identity_type_families the EKS and EKS_Cluster rows are two clusters by one name: no guess.
    dup = [_aws(1, "EKS", CL), _aws(2, "EKS_Cluster", f"arn:aws:eks:{REGION}:111122223333:cluster/{CL}"),
           _k(10, "Namespace", "shop")]
    assert ("acct:1", "res:10", "contains") in _edges(derive_rule_graph(dup), "contains")


def test_service_routes_to_the_workloads_its_selector_picks_in_its_namespace():
    g = _derive([
        _k(20, "Service", "checkout", "shop", selector={"app": "checkout"}),
        _k(21, "Deployment", "checkout", "shop", template_labels={"app": "checkout", "tier": "web"}),
        _k(22, "Deployment", "cart", "shop", template_labels={"app": "cart"}),
        _k(23, "Deployment", "checkout", "other", template_labels={"app": "checkout"}),
        _k(24, "Service", "headless", "shop", selector=None),
        _k(25, "Service", "empty", "shop", selector={}),
    ])
    assert _edges(g, "routes_to") == {("res:20", "res:21", "routes_to")}
    edge = next(e for e in g["edges"] if (e["source"], e["target"]) == ("res:20", "res:21"))
    assert edge["evidence"] == "raw_data.selector=app=checkout"


def test_ingress_routes_to_its_backend_services_in_the_same_namespace():
    g = _derive([
        _k(30, "Ingress", "web", "shop", backends=["checkout", "missing"]),
        _k(20, "Service", "checkout", "shop"),
        _k(26, "Service", "checkout", "other"),
    ])
    assert _edges(g, "routes_to") == {("res:30", "res:20", "routes_to")}


def test_workload_uses_its_configmaps_secrets_and_claims_and_reports_the_missing():
    g = _derive([
        _k(40, "Deployment", "checkout", "shop",
           refs={"configmap": ["app-config", "gone-config"], "secret": ["db-pass"], "pvc": ["data"]}),
        _k(41, "ConfigMap", "app-config", "shop"),
        _k(42, "Secret", "db-pass", "shop"),
        _k(43, "PersistentVolumeClaim", "data", "shop"),
        _k(44, "ConfigMap", "gone-config", "other"),       # same name, other namespace: not a match
        _k(45, "StatefulSet", "db", "shop"),
    ])
    assert _edges(g, "uses") == {("res:40", "res:41", "uses"), ("res:40", "res:42", "uses"),
                                 ("res:40", "res:43", "uses")}
    assert g["unresolved_refs"] == {40: [{"kind": "ConfigMap", "name": "gone-config"}], 45: []}


def test_network_policies_and_pdbs_restrict_the_workloads_they_select():
    g = _derive([
        _k(21, "Deployment", "checkout", "shop", template_labels={"app": "checkout"}),
        _k(22, "Deployment", "cart", "shop", template_labels={"app": "cart"}),
        _k(23, "Deployment", "checkout", "other", template_labels={"app": "checkout"}),
        _k(50, "NetworkPolicy", "deny-all", "shop", pod_selector={}),
        _k(51, "NetworkPolicy", "checkout-only", "shop", pod_selector={"app": "checkout"}),
        _k(52, "PodDisruptionBudget", "checkout-pdb", "shop", selector={"app": "checkout"}),
        _k(53, "PodDisruptionBudget", "expr-pdb", "shop", selector={"app": "checkout"}, selector_has_expressions=True),
        _k(54, "NetworkPolicy", "unset", "shop", pod_selector=None),
    ])
    assert _edges(g, "restricts") == {
        ("res:50", "res:21", "restricts"), ("res:50", "res:22", "restricts"),
        ("res:51", "res:21", "restricts"), ("res:52", "res:21", "restricts")}


def test_workloads_run_on_their_nodes_and_nodes_are_their_ec2_instances():
    g = _derive([
        _k(60, "Node", "ip-a", provider_id="aws:///us-east-1a/i-0abc123"),
        _aws(61, "EC2", "i-0abc123"),
        _k(62, "Deployment", "checkout", "shop", pod_summary={"nodes": ["ip-a", "ip-a", "ip-missing"]}),
        _k(63, "Pod", "stress-test", "shop", pod_summary={"nodes": ["ip-a"]}),
        _k(64, "Node", "ip-b", provider_id="aws:///us-east-1a/i-0fff"),
        _aws(65, "EC2", "i-0fff", account_id=2),               # same instance id, other account
    ])
    assert _edges(g, "runs_on") == {("res:62", "res:60", "runs_on"), ("res:63", "res:60", "runs_on")}
    assert _edges(g, "same_as") == {("res:60", "res:61", "same_as")}


def test_load_balancer_routes_to_the_service_that_publishes_its_dns_name():
    g = _derive([
        _aws(70, "ELB", "web-alb", raw={"DNSName": "web-alb-123.us-east-1.elb.amazonaws.com"}),
        _k(71, "Service", "checkout", "shop", type="LoadBalancer",
           load_balancer_hostnames=["WEB-ALB-123.us-east-1.elb.amazonaws.com", "other.elb.amazonaws.com"]),
        _aws(72, "ELB", "web-alb", raw={"DNSName": "web-alb-123.us-east-1.elb.amazonaws.com"}, account_id=2),
    ])
    assert _edges(g, "routes_to") == {("res:70", "res:71", "routes_to")}


def test_absent_rows_keep_their_last_seen_relations():
    svc = _k(20, "Service", "checkout", "shop", selector={"app": "checkout"})
    svc["absent_since"] = datetime(2026, 9, 27)
    g = _derive([svc, _k(21, "Deployment", "checkout", "shop", template_labels={"app": "checkout"})])
    assert ("res:20", "res:21", "routes_to") in _edges(g)


def test_k8s_edges_are_registered_unique_and_point_the_registry_way():
    from agenticops.graph import relations

    g = _derive([
        _k(10, "Namespace", "shop"),
        _k(20, "Service", "checkout", "shop", selector={"app": "checkout"}),
        _k(21, "Deployment", "checkout", "shop", template_labels={"app": "checkout"},
           refs={"configmap": ["app-config"]}, pod_summary={"nodes": ["ip-a"]}),
        _k(41, "ConfigMap", "app-config", "shop"),
        _k(51, "NetworkPolicy", "checkout-only", "shop", pod_selector={"app": "checkout"}),
        _k(60, "Node", "ip-a"),
    ])
    edges = [(e["source"], e["target"], e["relation_type"]) for e in g["edges"]]
    assert len(edges) == len(set(edges))
    assert {t for _, _, t in edges} <= relations.RULE_RELATION_TYPES
    # What can break the workload: its namespace, its config, the policy on it and the node under it.
    assert relations.upstream_of("res:21", edges) == {"res:10", "res:41", "res:51", "res:60"}
    # What it breaks: the Service that routes to it.
    assert relations.downstream_of("res:21", edges) == {"res:20"}


def test_every_k8s_type_is_excluded_from_llm_enrichment():
    from agenticops.config import settings
    from agenticops.galaxy.rules import K8S_TYPES

    assert len(K8S_TYPES) == 13
    assert K8S_TYPES <= set(settings.galaxy_llm_exclude_types)
