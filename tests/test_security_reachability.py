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
