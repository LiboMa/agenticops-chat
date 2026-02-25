"""Live AWS integration tests for EKS networking tools.

These tests call real AWS APIs and require valid credentials.
EKS tests skip gracefully if no clusters exist in the region.
Run with: uv run pytest tests/integration/ -v --run-integration
"""

import json

import pytest

from agenticops.tools.eks_tools import (
    describe_eks_clusters,
    describe_eks_nodegroups,
    check_eks_pod_ip_capacity,
    map_eks_to_vpc_topology,
)


def _get_first_cluster_name(region: str) -> str | None:
    """Helper to find a cluster for testing; returns None if none exist."""
    result = describe_eks_clusters(region=region)
    data = json.loads(result)
    if isinstance(data, dict) and "error" in data:
        return None
    if not data:
        return None
    return data[0]["name"]


@pytest.mark.integration
class TestEksToolsLive:
    """Integration tests for EKS networking tools."""

    def test_describe_eks_clusters_live(self, aws_region):
        """Describe EKS clusters returns valid JSON."""
        result = describe_eks_clusters(region=aws_region)
        data = json.loads(result)
        # Either a list of clusters or an empty list
        if isinstance(data, list):
            if data:
                assert "name" in data[0]
                assert "vpc_config" in data[0]
        else:
            # Error dict is also acceptable if no EKS permissions
            assert isinstance(data, dict)

    def test_describe_eks_nodegroups_live(self, aws_region):
        """Describe nodegroups for a cluster (skips if no clusters)."""
        cluster_name = _get_first_cluster_name(aws_region)
        if not cluster_name:
            pytest.skip("No EKS clusters in region")

        result = describe_eks_nodegroups(region=aws_region, cluster_name=cluster_name)
        data = json.loads(result)

        if isinstance(data, list):
            if data:
                assert "nodegroup_name" in data[0]
                assert "instance_types" in data[0]
        else:
            assert isinstance(data, dict)

    def test_check_eks_pod_ip_capacity_live(self, aws_region):
        """Check pod IP capacity for a cluster (skips if no clusters)."""
        cluster_name = _get_first_cluster_name(aws_region)
        if not cluster_name:
            pytest.skip("No EKS clusters in region")

        result = check_eks_pod_ip_capacity(region=aws_region, cluster_name=cluster_name)
        data = json.loads(result)

        if "error" not in data:
            assert "cluster_name" in data
            assert "total_cluster_pod_capacity" in data
            assert "warnings" in data

    def test_map_eks_to_vpc_topology_live(self, aws_region):
        """Map EKS to VPC topology (skips if no clusters)."""
        cluster_name = _get_first_cluster_name(aws_region)
        if not cluster_name:
            pytest.skip("No EKS clusters in region")

        result = map_eks_to_vpc_topology(region=aws_region, cluster_name=cluster_name)
        data = json.loads(result)

        if "error" not in data:
            assert "cluster_name" in data
            assert "vpc_id" in data
            assert "subnet_topology" in data
            assert "topology_issues" in data
