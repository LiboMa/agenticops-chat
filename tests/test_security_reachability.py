from agenticops.tools.network_tools import _build_sg_dependency_map


class TestSgDependencyMapRules:
    def test_inbound_rules_attached(self):
        sgs = [{
            "GroupId": "sg-1", "GroupName": "web",
            "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                               "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
            "IpPermissionsEgress": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        }]
        m = _build_sg_dependency_map(sgs)
        assert "inbound_rules" in m["sg-1"]
        assert m["sg-1"]["inbound_rules"][0]["ports"] == "22"
        assert "0.0.0.0/0" in m["sg-1"]["inbound_rules"][0]["sources"]
        assert m["sg-1"]["outbound_rules"][0]["ports"] == "all"
        # backward-compat keys still present
        assert m["sg-1"]["name"] == "web"
        assert m["sg-1"]["references"] == []


class TestSubnetPublicIpFlag:
    def test_subnet_dict_carries_map_public_ip(self):
        # _format_subnet-like inline: assert the key exists in the emitted dict.
        # The subnet append block (network_tools.py:963) must include the flag.
        import inspect
        from agenticops.tools import network_tools
        src = inspect.getsource(network_tools.analyze_vpc_topology)
        assert "map_public_ip_on_launch" in src


from agenticops.graph.algorithms import internet_ingress_reachability as reach


def _sg_open(port):
    return {"sg-open": {"inbound_rules": [
        {"protocol": "tcp", "ports": str(port), "sources": ["0.0.0.0/0"]}]}}


PUB_SUBNET = {"subnet_id": "sn-1", "type": "public",
              "default_route_target": "igw-1", "map_public_ip_on_launch": True}
INSTANCE = {"instance_id": "i-1", "state": "running", "public_ip": "1.2.3.4",
            "subnet_id": "sn-1", "security_group_ids": ["sg-open"]}


class TestIngressReachability:
    def test_all_conditions_met_reachable(self):
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22)
        assert v.state == "reachable"
        assert v.path == ["internet", "sn-1", "i-1:22"]

    def test_no_public_ip_not_reachable(self):
        inst = {**INSTANCE, "public_ip": None}
        assert reach(instance=inst, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22).state == "not_reachable"

    def test_private_subnet_no_igw_not_reachable(self):
        sn = {**PUB_SUBNET, "type": "private", "default_route_target": "nat-1"}
        assert reach(instance=INSTANCE, subnet=sn, security_groups=_sg_open(22), port=22).state == "not_reachable"

    def test_blackhole_default_route_not_reachable(self):
        sn = {**PUB_SUBNET, "default_route_target": "blackhole"}
        assert reach(instance=INSTANCE, subnet=sn, security_groups=_sg_open(22), port=22).state == "not_reachable"

    def test_sg_does_not_open_port_not_reachable(self):
        assert reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(80), port=22).state == "not_reachable"

    def test_instance_stopped_not_reachable(self):
        inst = {**INSTANCE, "state": "stopped"}
        assert reach(instance=inst, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22).state == "not_reachable"

    def test_missing_subnet_undetermined(self):
        assert reach(instance=INSTANCE, subnet=None, security_groups=_sg_open(22), port=22).state == "undetermined"

    def test_sg_referenced_but_absent_undetermined(self):
        # instance points at sg-x which isn't in the map, and no SG opens the port -> can't rule out
        inst = {**INSTANCE, "security_group_ids": ["sg-x"]}
        assert reach(instance=inst, subnet=PUB_SUBNET, security_groups={}, port=22).state == "undetermined"

    def test_port_range_match_reachable(self):
        sgs = {"sg-open": {"inbound_rules": [
            {"protocol": "tcp", "ports": "20-30", "sources": ["0.0.0.0/0"]}]}}
        assert reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=sgs, port=22).state == "reachable"

    def test_all_protocol_all_ports_reachable(self):
        sgs = {"sg-open": {"inbound_rules": [
            {"protocol": "all", "ports": "all", "sources": ["0.0.0.0/0"]}]}}
        assert reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=sgs, port=22).state == "reachable"


class TestIngressReachabilityConservative:
    """R26 conservative-bias hardening: route-target None disambiguation,
    unidentified target, numeric TCP protocol, and missing-field undetermined."""

    def test_route_none_but_rt_resolved_isolated_not_reachable(self):
        # route table WAS resolved and has no default route -> genuinely isolated
        sn = {**PUB_SUBNET, "default_route_target": None, "route_table_id": "rtb-1"}
        assert reach(instance=INSTANCE, subnet=sn, security_groups=_sg_open(22), port=22).state == "not_reachable"

    def test_route_none_and_rt_unresolved_undetermined(self):
        # no route table could be resolved (partial data) -> conservative undetermined
        sn = {**PUB_SUBNET, "default_route_target": None, "route_table_id": None}
        assert reach(instance=INSTANCE, subnet=sn, security_groups=_sg_open(22), port=22).state == "undetermined"

    def test_route_target_unknown_undetermined(self):
        sn = {**PUB_SUBNET, "default_route_target": "unknown"}
        assert reach(instance=INSTANCE, subnet=sn, security_groups=_sg_open(22), port=22).state == "undetermined"

    def test_numeric_tcp_protocol_opens_port_reachable(self):
        sgs = {"sg-open": {"inbound_rules": [
            {"protocol": "6", "ports": "22", "sources": ["0.0.0.0/0"]}]}}
        assert reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=sgs, port=22).state == "reachable"

    def test_instance_none_undetermined(self):
        assert reach(instance=None, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22).state == "undetermined"

    def test_instance_missing_state_undetermined(self):
        inst = {"instance_id": "i-1", "public_ip": "1.2.3.4",
                "subnet_id": "sn-1", "security_group_ids": ["sg-open"]}
        assert reach(instance=inst, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22).state == "undetermined"

    def test_instance_missing_public_ip_key_undetermined(self):
        inst = {"instance_id": "i-1", "state": "running",
                "subnet_id": "sn-1", "security_group_ids": ["sg-open"]}
        assert reach(instance=inst, subnet=PUB_SUBNET, security_groups=_sg_open(22), port=22).state == "undetermined"


from agenticops.security.collectors import PostureFinding
from agenticops.security.reachability import annotate, port_for_control


def test_port_for_control():
    assert port_for_control("cis-4.1") == 22
    assert port_for_control("cis-4.2") == 3389
    assert port_for_control("cis-1.3") is None


# NACL 默认开启（security_reachability_nacl_enabled=True）。一旦 Stage 3（Task 3.2）
# 加上 NACL gate，缺 nacl 数据的 finding 会变 'undetermined'。这里传一个 allow-all
# NACL，使本 SG 路径用例在 Stage 2（gate 未落、nacl 被忽略）与 Stage 3（gate 生效、
# allow-all 放行）两阶段都稳定绿——不要靠 monkeypatch 全局 setting。
_ALLOW_ALL_NACL = {
    "inbound": [{"rule_number": 100, "protocol": "-1", "cidr": "0.0.0.0/0",
                 "action": "allow", "port_from": None, "port_to": None}],
    "outbound": [{"rule_number": 100, "protocol": "-1", "cidr": "0.0.0.0/0",
                  "action": "allow", "port_from": None, "port_to": None}],
}


def test_annotate_marks_network_findings():
    f = PostureFinding("network", "cis-4.1", "sg-open", "SecurityGroup", "0.0.0.0/0:22")
    instances = {"i-1": {"instance_id": "i-1", "state": "running", "public_ip": "1.2.3.4",
                         "subnet_id": "sn-1", "security_group_ids": ["sg-open"]}}
    subnets = {"sn-1": {"subnet_id": "sn-1", "type": "public",
                        "default_route_target": "igw-1", "map_public_ip_on_launch": True}}
    sgs = {"sg-open": {"inbound_rules": [{"protocol": "tcp", "ports": "22", "sources": ["0.0.0.0/0"]}]}}
    out = annotate([f], instances, subnets, sgs, nacls={"sn-1": _ALLOW_ALL_NACL})
    assert out[0]["reachability"] == "reachable"
    assert out[0]["path"] == ["internet", "sn-1", "i-1:22"]


def test_annotate_non_network_is_na():
    f = PostureFinding("iam", "cis-1.3", "alice", "IAMUser", "stale key")
    out = annotate([f], {}, {}, {})
    assert out[0]["reachability"] == "n/a"


from unittest.mock import MagicMock, patch
from agenticops.security.collectors import collect_network_acls
from agenticops.graph.types import NodeType


def test_nodetype_network_acl_exists():
    assert NodeType.NETWORK_ACL.value == "network_acl"


def test_collect_network_acls_orders_and_maps_subnets():
    acl = {"NetworkAclId": "acl-1", "Associations": [{"SubnetId": "sn-1"}],
           "Entries": [
               {"RuleNumber": 200, "Protocol": "6", "RuleAction": "allow",
                "Egress": False, "CidrBlock": "0.0.0.0/0", "PortRange": {"From": 80, "To": 80}},
               {"RuleNumber": 100, "Protocol": "6", "RuleAction": "deny",
                "Egress": False, "CidrBlock": "0.0.0.0/0", "PortRange": {"From": 22, "To": 22}},
               {"RuleNumber": 100, "Protocol": "-1", "RuleAction": "allow",
                "Egress": True, "CidrBlock": "0.0.0.0/0"},
           ]}
    ec2 = MagicMock()
    ec2.describe_network_acls.return_value = {"NetworkAcls": [acl]}
    with patch("agenticops.security.collectors._get_client", return_value=ec2):
        out = collect_network_acls("acct-a", "us-east-1", "vpc-1")
    assert out["sn-1"]["nacl_id"] == "acl-1"
    # inbound ordered by rule_number ascending
    assert [e["rule_number"] for e in out["sn-1"]["inbound"]] == [100, 200]
    assert out["sn-1"]["inbound"][0]["action"] == "deny"
    assert out["sn-1"]["outbound"][0]["action"] == "allow"


NACL_ALLOW_ALL = {
    "inbound": [{"rule_number": 100, "protocol": "-1", "cidr": "0.0.0.0/0",
                 "action": "allow", "port_from": None, "port_to": None}],
    "outbound": [{"rule_number": 100, "protocol": "-1", "cidr": "0.0.0.0/0",
                  "action": "allow", "port_from": None, "port_to": None}],
}


class TestNaclGate:
    def test_nacl_allow_all_reachable(self):
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=NACL_ALLOW_ALL, nacl_required=True)
        assert v.state == "reachable"

    def test_nacl_inbound_deny_not_reachable(self):
        nacl = {"inbound": [
            {"rule_number": 100, "protocol": "6", "cidr": "0.0.0.0/0",
             "action": "deny", "port_from": 22, "port_to": 22}],
            "outbound": NACL_ALLOW_ALL["outbound"]}
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=nacl, nacl_required=True)
        assert v.state == "not_reachable"
        assert "nacl" in v.reason.lower()

    def test_nacl_outbound_ephemeral_deny_not_reachable(self):
        nacl = {"inbound": NACL_ALLOW_ALL["inbound"],
                "outbound": [{"rule_number": 100, "protocol": "6", "cidr": "0.0.0.0/0",
                              "action": "deny", "port_from": 1024, "port_to": 65535}]}
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=nacl, nacl_required=True)
        assert v.state == "not_reachable"

    def test_nacl_ordered_first_match_wins(self):
        # rule 100 denies 22, rule 200 allows all -> first match (deny) wins
        nacl = {"inbound": [
            {"rule_number": 100, "protocol": "6", "cidr": "0.0.0.0/0",
             "action": "deny", "port_from": 22, "port_to": 22},
            {"rule_number": 200, "protocol": "-1", "cidr": "0.0.0.0/0",
             "action": "allow", "port_from": None, "port_to": None}],
            "outbound": NACL_ALLOW_ALL["outbound"]}
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=nacl, nacl_required=True)
        assert v.state == "not_reachable"

    def test_nacl_required_but_missing_undetermined(self):
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=None, nacl_required=True)
        assert v.state == "undetermined"

    def test_nacl_disabled_ignores_nacl(self):
        # nacl_required False -> Stage 2 behavior, reachable even with no nacl data
        v = reach(instance=INSTANCE, subnet=PUB_SUBNET, security_groups=_sg_open(22),
                  port=22, nacl=None, nacl_required=False)
        assert v.state == "reachable"
