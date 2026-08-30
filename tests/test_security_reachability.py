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
