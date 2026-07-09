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
