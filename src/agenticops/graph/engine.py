"""Infrastructure Graph Engine — builds and queries NetworkX graphs from topology data."""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from agenticops.graph.types import (
    EdgeAttrs,
    EdgeType,
    NodeAttrs,
    NodeStatus,
    NodeType,
)

logger = logging.getLogger(__name__)


class InfraGraph:
    """NetworkX-backed infrastructure graph.

    Consumes the JSON output of existing network_tools.py functions
    (analyze_vpc_topology, describe_region_topology) and builds a typed
    directed graph for algorithmic queries.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    # ── Builder methods ──────────────────────────────────────────────

    def _add_node(self, node_id: str, attrs: NodeAttrs) -> None:
        self._graph.add_node(node_id, **attrs.model_dump())

    def _add_edge(self, source: str, target: str, attrs: EdgeAttrs) -> None:
        self._graph.add_edge(source, target, **attrs.model_dump())

    def build_from_vpc_topology(self, topo: dict[str, Any]) -> InfraGraph:
        """Build graph from analyze_vpc_topology() JSON output.

        Mapping rules:
        - VPC node (1)
        - IGW nodes + ATTACHED_TO edge -> VPC
        - Subnet nodes + CONTAINS edge <- VPC
        - RouteTable nodes + ASSOCIATED_WITH edge <- Subnet
        - Route entries -> ROUTES_TO edges
        - NAT nodes + HOSTED_IN edge -> Subnet
        - TGW attachment nodes + ATTACHED_TO edge -> VPC
        - Peering nodes + PEERS_WITH edges -> VPCs
        - Endpoint nodes + HOSTED_IN edge -> Subnet
        - SG nodes + REFERENCES edges
        """
        vpc_id = topo.get("vpc_id", "")
        vpc_cidr = topo.get("vpc_cidr", "")
        vpc_name = topo.get("vpc_name") or vpc_id

        # VPC node
        self._add_node(vpc_id, NodeAttrs(
            node_type=NodeType.VPC,
            label=vpc_name,
            status=NodeStatus.HEALTHY,
            resource_type="VPC",
            raw={"vpc_id": vpc_id, "cidr": vpc_cidr},
        ))

        # Internet Gateways
        for igw in topo.get("internet_gateways", []):
            igw_id = igw["igw_id"]
            attachments = igw.get("attachments", [])
            status = self._derive_igw_status(attachments)
            self._add_node(igw_id, NodeAttrs(
                node_type=NodeType.INTERNET_GATEWAY,
                label=igw.get("name") or igw_id,
                status=status,
                resource_type="Internet Gateway",
                raw=igw,
            ))
            self._add_edge(igw_id, vpc_id, EdgeAttrs(
                edge_type=EdgeType.ATTACHED_TO,
                label="attached",
            ))

        # Subnets
        for subnet in topo.get("subnets", []):
            subnet_id = subnet["subnet_id"]
            subnet_status = self._derive_subnet_status(subnet)
            self._add_node(subnet_id, NodeAttrs(
                node_type=NodeType.SUBNET,
                label=subnet.get("name") or subnet_id,
                status=subnet_status,
                resource_type=f"{subnet.get('type', 'private').title()} Subnet",
                raw=subnet,
            ))
            self._add_edge(vpc_id, subnet_id, EdgeAttrs(
                edge_type=EdgeType.CONTAINS,
                label="contains",
            ))

        # Route Tables
        for rtb in topo.get("route_tables", []):
            rtb_id = rtb["route_table_id"]
            has_blackhole = any(r.get("state") == "blackhole" for r in rtb.get("routes", []))
            rtb_status = NodeStatus.ERROR if has_blackhole else NodeStatus.HEALTHY
            self._add_node(rtb_id, NodeAttrs(
                node_type=NodeType.ROUTE_TABLE,
                label=rtb.get("name") or rtb_id,
                status=rtb_status,
                resource_type="Route Table",
                raw=rtb,
            ))
            # Subnet -> RouteTable associations
            for assoc_subnet_id in rtb.get("associated_subnets", []):
                if self._graph.has_node(assoc_subnet_id):
                    self._add_edge(assoc_subnet_id, rtb_id, EdgeAttrs(
                        edge_type=EdgeType.ASSOCIATED_WITH,
                        label="associated",
                    ))

        # Build TGW lookup: transit_gateway_id -> attachment_id
        tgw_lookup: dict[str, str] = {}
        for att in topo.get("transit_gateway_attachments", []):
            tgw_lookup[att.get("transit_gateway_id", "")] = att["attachment_id"]

        # Route entries -> ROUTES_TO edges
        blackhole_set: set[str] = set()
        for bh in topo.get("blackhole_routes", []):
            blackhole_set.add(f"{bh['route_table_id']}:{bh['destination']}")

        for rtb in topo.get("route_tables", []):
            rtb_id = rtb["route_table_id"]
            for route in rtb.get("routes", []):
                target = route.get("target", "")
                if target == "local":
                    continue

                resolved_target = target
                if target.startswith("tgw-"):
                    resolved_target = tgw_lookup.get(target, target)

                if not self._graph.has_node(resolved_target):
                    continue

                is_blackhole = (
                    route.get("state") == "blackhole"
                    or f"{rtb_id}:{route.get('destination', '')}" in blackhole_set
                )

                self._add_edge(rtb_id, resolved_target, EdgeAttrs(
                    edge_type=EdgeType.ROUTES_TO,
                    label=route.get("destination", ""),
                    state="blackhole" if is_blackhole else "active",
                ))

        # NAT Gateways
        for nat in topo.get("nat_gateways", []):
            nat_id = nat["nat_gateway_id"]
            nat_status = self._derive_nat_status(nat)
            self._add_node(nat_id, NodeAttrs(
                node_type=NodeType.NAT_GATEWAY,
                label=nat.get("name") or nat_id,
                status=nat_status,
                resource_type="NAT Gateway",
                raw=nat,
            ))
            nat_subnet = nat.get("subnet_id", "")
            if nat_subnet and self._graph.has_node(nat_subnet):
                self._add_edge(nat_id, nat_subnet, EdgeAttrs(
                    edge_type=EdgeType.HOSTED_IN,
                    label="hosted in",
                ))

        # Transit Gateway Attachments
        for att in topo.get("transit_gateway_attachments", []):
            att_id = att["attachment_id"]
            att_status = self._derive_tgw_status(att)
            self._add_node(att_id, NodeAttrs(
                node_type=NodeType.TGW_ATTACHMENT,
                label=att.get("transit_gateway_id", att_id),
                status=att_status,
                resource_type="Transit Gateway",
                raw=att,
            ))
            self._add_edge(att_id, vpc_id, EdgeAttrs(
                edge_type=EdgeType.ATTACHED_TO,
                label="attached",
            ))

        # VPC Peering Connections
        for pcx in topo.get("vpc_peering_connections", []):
            pcx_id = pcx["pcx_id"]
            pcx_status = self._derive_peering_status(pcx)
            self._add_node(pcx_id, NodeAttrs(
                node_type=NodeType.PEERING,
                label=pcx_id,
                status=pcx_status,
                resource_type="VPC Peering",
                raw=pcx,
            ))
            req_vpc = pcx.get("requester_vpc", "")
            acc_vpc = pcx.get("accepter_vpc", "")
            if req_vpc == vpc_id or acc_vpc == vpc_id:
                self._add_edge(pcx_id, vpc_id, EdgeAttrs(
                    edge_type=EdgeType.PEERS_WITH,
                    label="peers with",
                ))

        # VPC Endpoints
        for vpce in topo.get("vpc_endpoints", []):
            vpce_id = vpce["endpoint_id"]
            vpce_status = self._derive_endpoint_status(vpce)
            service_name = vpce.get("service_name", "")
            short_name = service_name.split(".")[-1] if service_name else vpce_id
            self._add_node(vpce_id, NodeAttrs(
                node_type=NodeType.VPC_ENDPOINT,
                label=short_name,
                status=vpce_status,
                resource_type="VPC Endpoint",
                raw=vpce,
            ))
            for sid in vpce.get("subnet_ids", []):
                if self._graph.has_node(sid):
                    self._add_edge(vpce_id, sid, EdgeAttrs(
                        edge_type=EdgeType.HOSTED_IN,
                        label="endpoint",
                    ))

        # Security Group Dependencies
        sg_map = topo.get("security_group_dependency_map", {})
        for sg_id, sg_data in sg_map.items():
            if isinstance(sg_data, dict):
                self._add_node(sg_id, NodeAttrs(
                    node_type=NodeType.SECURITY_GROUP,
                    label=sg_data.get("name", sg_id),
                    status=NodeStatus.HEALTHY,
                    resource_type="Security Group",
                    raw=sg_data,
                ))
                for ref_sg in sg_data.get("references", []):
                    if ref_sg in sg_map:
                        if not self._graph.has_node(ref_sg):
                            ref_data = sg_map.get(ref_sg, {})
                            if isinstance(ref_data, dict):
                                self._add_node(ref_sg, NodeAttrs(
                                    node_type=NodeType.SECURITY_GROUP,
                                    label=ref_data.get("name", ref_sg),
                                    status=NodeStatus.HEALTHY,
                                    resource_type="Security Group",
                                    raw=ref_data,
                                ))
                        self._add_edge(sg_id, ref_sg, EdgeAttrs(
                            edge_type=EdgeType.REFERENCES,
                            label="references",
                        ))

        return self

    def build_from_region_topology(self, topo: dict[str, Any]) -> InfraGraph:
        """Build graph from describe_region_topology() JSON output."""
        region = topo.get("region", "")
        region_vpc_ids = set()

        # VPC nodes
        for vpc in topo.get("vpcs", []):
            vpc_id = vpc["vpc_id"]
            region_vpc_ids.add(vpc_id)
            self._add_node(vpc_id, NodeAttrs(
                node_type=NodeType.VPC,
                label=vpc.get("name") or vpc_id,
                status=NodeStatus.HEALTHY,
                resource_type="VPC",
                raw=vpc,
            ))

        # Transit Gateways
        for tgw in topo.get("transit_gateways", []):
            tgw_id = tgw["transit_gateway_id"]
            state = tgw.get("state", "unknown")
            status = NodeStatus.HEALTHY if state == "available" else NodeStatus.WARNING
            self._add_node(tgw_id, NodeAttrs(
                node_type=NodeType.TRANSIT_GATEWAY,
                label=tgw.get("name") or tgw_id,
                status=status,
                resource_type="Transit Gateway",
                raw=tgw,
            ))
            for att in tgw.get("attachments", []):
                res_id = att.get("resource_id", "")
                if att.get("resource_type") == "vpc" and res_id in region_vpc_ids:
                    self._add_edge(tgw_id, res_id, EdgeAttrs(
                        edge_type=EdgeType.ATTACHED_TO,
                        label=att.get("state", ""),
                    ))

        # Peering Connections
        for pcx in topo.get("peering_connections", []):
            pcx_id = pcx["pcx_id"]
            req_vpc = pcx.get("requester_vpc", "")
            acc_vpc = pcx.get("accepter_vpc", "")

            src_in = req_vpc in region_vpc_ids
            dst_in = acc_vpc in region_vpc_ids

            if src_in and dst_in:
                self._add_edge(req_vpc, acc_vpc, EdgeAttrs(
                    edge_type=EdgeType.PEERS_WITH,
                    label=pcx_id,
                    state=pcx.get("status", ""),
                ))
            elif src_in or dst_in:
                local_vpc = req_vpc if src_in else acc_vpc
                remote_vpc = acc_vpc if src_in else req_vpc
                remote_cidr = pcx.get("accepter_cidr" if src_in else "requester_cidr", "")

                if not self._graph.has_node(remote_vpc):
                    self._add_node(remote_vpc, NodeAttrs(
                        node_type=NodeType.VPC,
                        label=f"{remote_vpc} (external)",
                        status=NodeStatus.UNKNOWN,
                        resource_type="VPC",
                        raw={"vpc_id": remote_vpc, "cidr": remote_cidr, "state": "external"},
                    ))

                self._add_edge(local_vpc, remote_vpc, EdgeAttrs(
                    edge_type=EdgeType.PEERS_WITH,
                    label=pcx_id,
                    state=pcx.get("status", ""),
                ))

        return self

    def merge(self, other: InfraGraph) -> InfraGraph:
        """Merge another graph into this one (for multi-VPC analysis)."""
        self._graph = nx.compose(self._graph, other._graph)
        return self

    # ── Query methods ────────────────────────────────────────────────

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        if node_id in self._graph:
            return dict(self._graph.nodes[node_id])
        return None

    def get_neighbors(
        self, node_id: str, edge_type: EdgeType | None = None
    ) -> list[str]:
        if node_id not in self._graph:
            return []
        neighbors = []
        for _, target, data in self._graph.out_edges(node_id, data=True):
            if edge_type is None or data.get("edge_type") == edge_type:
                neighbors.append(target)
        for source, _, data in self._graph.in_edges(node_id, data=True):
            if edge_type is None or data.get("edge_type") == edge_type:
                neighbors.append(source)
        return neighbors

    def get_nodes_by_type(self, node_type: NodeType) -> list[str]:
        return [
            n for n, d in self._graph.nodes(data=True)
            if d.get("node_type") == node_type
        ]

    def subgraph(self, node_ids: set[str]) -> InfraGraph:
        sub = InfraGraph()
        sub._graph = self._graph.subgraph(node_ids).copy()
        return sub

    # ── Status derivation helpers ────────────────────────────────────

    @staticmethod
    def _derive_igw_status(attachments: list[dict[str, Any]]) -> NodeStatus:
        if not attachments:
            return NodeStatus.ERROR
        state = attachments[0].get("state", "")
        if state == "attached":
            return NodeStatus.HEALTHY
        if state == "detaching":
            return NodeStatus.WARNING
        return NodeStatus.ERROR

    @staticmethod
    def _derive_subnet_status(subnet: dict[str, Any]) -> NodeStatus:
        ips = subnet.get("available_ips")
        if ips is None:
            return NodeStatus.UNKNOWN
        if ips >= 10:
            return NodeStatus.HEALTHY
        if ips >= 5:
            return NodeStatus.WARNING
        return NodeStatus.ERROR

    @staticmethod
    def _derive_nat_status(nat: dict[str, Any]) -> NodeStatus:
        state = nat.get("state", "")
        if state == "available":
            return NodeStatus.HEALTHY
        if state == "pending":
            return NodeStatus.WARNING
        if state in ("failed", "deleted", "deleting"):
            return NodeStatus.ERROR
        return NodeStatus.UNKNOWN

    @staticmethod
    def _derive_tgw_status(att: dict[str, Any]) -> NodeStatus:
        state = att.get("state", "")
        if state == "available":
            return NodeStatus.HEALTHY
        if state in ("modifying", "pendingAcceptance"):
            return NodeStatus.WARNING
        if state in ("failing", "deleting"):
            return NodeStatus.ERROR
        return NodeStatus.UNKNOWN

    @staticmethod
    def _derive_peering_status(pcx: dict[str, Any]) -> NodeStatus:
        status = pcx.get("status", "")
        if status == "active":
            return NodeStatus.HEALTHY
        if status in ("pending-acceptance", "provisioning"):
            return NodeStatus.WARNING
        if status in ("failed", "expired", "rejected"):
            return NodeStatus.ERROR
        return NodeStatus.UNKNOWN

    @staticmethod
    def _derive_endpoint_status(vpce: dict[str, Any]) -> NodeStatus:
        state = vpce.get("state", "")
        if state == "available":
            return NodeStatus.HEALTHY
        if state in ("pending", "pendingAcceptance"):
            return NodeStatus.WARNING
        if state in ("failed", "rejected", "deleted"):
            return NodeStatus.ERROR
        return NodeStatus.UNKNOWN
