"""L1 rule derivation: containment, ID references, tag grouping, provenance=rule."""

from agenticops.galaxy.rules import derive_rule_graph, resource_node_id, group_node_id, group_slug


def _r(pk, rtype, rid, raw=None, tags=None, account_id=1):
    return {"id": pk, "account_id": account_id, "provider": "aws", "region": "cn-north-1",
            "resource_type": rtype, "resource_id": rid, "name": rid,
            "tags": tags or {}, "raw_data": raw or {}}


def test_node_ids():
    assert resource_node_id(7) == "res:7"
    assert group_node_id("1:project:demo") == "grp:1:project:demo"
    assert group_slug(1, "project", "demo") == "1:project:demo"


def test_account_contains_vpc():
    g = derive_rule_graph([_r(1, "VPC", "vpc-a")])
    edges = g["edges"]
    assert any(e["relation_type"] == "contains" and e["source"] == "acct:1"
               and e["target"] == "res:1" and e["provenance"] == "rule" for e in edges)


def test_vpc_contains_subnet():
    g = derive_rule_graph([
        _r(1, "VPC", "vpc-a"),
        _r(2, "Subnet", "subnet-a", raw={"VpcId": "vpc-a"}),
    ])
    assert any(e["source"] == "res:1" and e["target"] == "res:2"
               and e["relation_type"] == "contains" for e in g["edges"])


def test_subnet_contains_instance_via_nested_id():
    g = derive_rule_graph([
        _r(1, "VPC", "vpc-a"),
        _r(2, "Subnet", "subnet-a", raw={"VpcId": "vpc-a"}),
        _r(3, "EC2", "i-1", raw={"NetworkInterfaces": [{"SubnetId": "subnet-a", "VpcId": "vpc-a"}]}),
    ])
    assert any(e["source"] == "res:2" and e["target"] == "res:3"
               and e["relation_type"] == "contains" for e in g["edges"])


def test_instance_secured_by_group():
    g = derive_rule_graph([
        _r(1, "SecurityGroup", "sg-1", raw={"VpcId": "vpc-a"}),
        _r(2, "EC2", "i-1", raw={"NetworkInterfaces": [{"Groups": [{"GroupId": "sg-1"}]}]}),
    ])
    assert any(e["source"] == "res:2" and e["target"] == "res:1"
               and e["relation_type"] == "secured_by" for e in g["edges"])


def test_tag_grouping_member_of():
    g = derive_rule_graph([_r(1, "EC2", "i-1", tags={"Project": "demo"})])
    assert any(n["id"] == "grp:1:project:demo" and n["kind"] == "group" for n in g["nodes"])
    assert any(e["source"] == "res:1" and e["target"] == "grp:1:project:demo"
               and e["relation_type"] == "member_of" for e in g["edges"])
    assert any(gr["slug"] == "1:project:demo" and gr["kind"] == "project" for g_ in [g] for gr in g_["groups"])


def test_no_self_edges_and_dirty_tags_ignored():
    # A VPC whose raw_data echoes its own VpcId must not self-contain.
    g = derive_rule_graph([_r(1, "VPC", "vpc-a", raw={"VpcId": "vpc-a"}, tags="not-a-dict")])
    assert all(not (e["source"] == e["target"]) for e in g["edges"])


# ── MVP-2.6.1: account-scoped references and AWS rules (spec §3.A.3 ①②) ──


def _edge(g, src, dst, rtype):
    return [e for e in g["edges"] if (e["source"], e["target"], e["relation_type"]) == (src, dst, rtype)]


def _resource_edges(g):
    return [(e["source"], e["target"], e["relation_type"]) for e in g["edges"]
            if e["source"].startswith("res:") and e["target"].startswith("res:")]


def test_references_resolve_only_inside_the_account():
    g = derive_rule_graph([
        _r(1, "SecurityGroup", "sg-1", account_id=1),
        _r(2, "Subnet", "subnet-a", account_id=1),
        _r(3, "EC2", "i-1", account_id=2,
           raw={"NetworkInterfaces": [{"SubnetId": "subnet-a", "Groups": [{"GroupId": "sg-1"}]}]}),
        _r(4, "SecurityGroup", "sg-1", account_id=2),
    ])
    assert _edge(g, "res:3", "res:4", "secured_by")          # same account
    assert not _edge(g, "res:3", "res:1", "secured_by")      # same id, other account
    assert _edge(g, "acct:2", "res:3", "contains")           # subnet-a lives in account 1 only


def test_asg_manages_instances_and_classic_elb_routes_to_asg():
    g = derive_rule_graph([
        _r(1, "EC2", "i-1"),
        _r(2, "EC2", "i-2"),
        _r(3, "ELB", "classic-lb"),
        _r(4, "AutoScaling", "web-asg", raw={"Instances": [{"InstanceId": "i-1"}, {"InstanceId": "i-2"},
                                                             {"InstanceId": "i-gone"}],
                                             "LoadBalancerNames": ["classic-lb", "not-scanned"]}),
    ])
    assert _edge(g, "res:4", "res:1", "manages") and _edge(g, "res:4", "res:2", "manages")
    assert _edge(g, "res:3", "res:4", "routes_to")
    assert _edge(g, "res:4", "res:1", "manages")[0]["evidence"] == "raw_data.Instances[].InstanceId=i-1"
    assert len(_resource_edges(g)) == 3


def test_rds_is_contained_by_every_db_subnet_and_secured_by_its_vpc_groups():
    rds_raw = {"DBSubnetGroup": {"VpcId": "vpc-a", "Subnets": [{"SubnetIdentifier": "subnet-a"},
                                                                {"SubnetIdentifier": "subnet-b"}]},
               "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-db"}]}
    g = derive_rule_graph([
        _r(1, "VPC", "vpc-a"),
        _r(2, "Subnet", "subnet-a", raw={"VpcId": "vpc-a"}),
        _r(3, "Subnet", "subnet-b", raw={"VpcId": "vpc-a"}),
        _r(4, "SecurityGroup", "sg-db"),
        _r(5, "RDS", "weblab-mysql", raw=rds_raw),
    ])
    assert _edge(g, "res:2", "res:5", "contains") and _edge(g, "res:3", "res:5", "contains")
    assert not _edge(g, "res:1", "res:5", "contains")  # the subnets are the nearest parents
    assert _edge(g, "res:5", "res:4", "secured_by")


def test_rds_without_scanned_subnets_falls_back_to_its_vpc():
    g = derive_rule_graph([
        _r(1, "VPC", "vpc-a"),
        _r(5, "RDS", "db", raw={"DBSubnetGroup": {"VpcId": "vpc-a", "Subnets": [{"SubnetIdentifier": "subnet-x"}]}}),
    ])
    assert _edge(g, "res:1", "res:5", "contains")


def test_elb_subnets_and_security_groups():
    g = derive_rule_graph([
        _r(1, "Subnet", "subnet-a"),
        _r(2, "Subnet", "subnet-b"),
        _r(3, "SecurityGroup", "sg-lb"),
        _r(4, "ELB", "weblab-alb", raw={"AvailabilityZones": [{"SubnetId": "subnet-a"}, {"SubnetId": "subnet-b"},
                                                              {"SubnetId": "subnet-a"}],
                                        "SecurityGroups": ["sg-lb"]}),
    ])
    assert _edge(g, "res:1", "res:4", "contains") and _edge(g, "res:2", "res:4", "contains")
    assert _edge(g, "res:4", "res:3", "secured_by")
    assert len(_edge(g, "res:1", "res:4", "contains")) == 1  # listed twice, one edge


def test_lambda_uses_its_role_and_key_by_arn():
    role_arn = "arn:aws:iam::533267047935:role/service-role/resize-role"
    key_arn = "arn:aws:kms:us-east-1:533267047935:key/1111-2222"
    g = derive_rule_graph([
        _r(1, "IAMRole", "resize-role", raw={"Arn": role_arn}),
        _r(2, "KMS", "1111-2222", raw={"KeyId": "1111-2222", "KeyArn": key_arn}),
        _r(3, "Lambda", "arn:aws:lambda:us-east-1:533267047935:function:resize",
           raw={"Role": role_arn, "KMSKeyArn": key_arn}),
        _r(4, "Lambda", "arn:aws:lambda:us-east-1:533267047935:function:plain", raw={"Role": "arn:aws:iam::1:role/x"}),
    ])
    assert _edge(g, "res:3", "res:1", "uses") and _edge(g, "res:3", "res:2", "uses")
    assert not [e for e in _resource_edges(g) if e[0] == "res:4"]


def test_rows_without_the_fields_yield_no_resource_edges():
    g = derive_rule_graph([_r(i, t, f"x-{i}") for i, t in
                           enumerate(("AutoScaling", "RDS", "ELB", "Lambda", "EC2", "IAMRole"), start=1)])
    assert _resource_edges(g) == []


def test_rule_edges_are_registered_unique_and_point_the_registry_way():
    from agenticops.graph import relations

    g = derive_rule_graph([
        _r(1, "Subnet", "subnet-a"),
        _r(2, "SecurityGroup", "sg-1"),
        _r(3, "EC2", "i-1", raw={"NetworkInterfaces": [{"SubnetId": "subnet-a", "Groups": [{"GroupId": "sg-1"}]}],
                                 "SecurityGroups": [{"GroupId": "sg-1"}]}),
        _r(4, "AutoScaling", "asg", raw={"Instances": [{"InstanceId": "i-1"}]}),
    ])
    edges = _resource_edges(g)
    assert len(edges) == len(set(edges))
    assert {rtype for _, _, rtype in edges} <= relations.RULE_RELATION_TYPES
    assert relations.upstream_of("res:3", edges) == {"res:1", "res:2", "res:4"}
    assert relations.downstream_of("res:1", edges) == {"res:3"}
