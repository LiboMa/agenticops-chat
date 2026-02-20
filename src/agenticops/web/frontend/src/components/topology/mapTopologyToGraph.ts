import type { Node, Edge } from "@xyflow/react";
import type {
  VpcTopology,
  Subnet,
  TransitGatewayAttachment,
  BlackholeRoute,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Base data shape shared by all custom nodes                        */
/* ------------------------------------------------------------------ */

export interface BaseNodeData extends Record<string, unknown> {
  label: string;
  resourceType: string;
  /** Raw AWS resource object for the detail panel */
  raw: Record<string, unknown>;
  /** Future: whether this node has an issue (blackhole, etc.) */
  hasIssue?: boolean;
  /** Future: path-highlight support */
  highlighted?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Constants: dagre rank (layer) assignment                          */
/* ------------------------------------------------------------------ */

const RANK_EXTERNAL = 0; // IGW, TGW, Peering
const RANK_PUBLIC = 1; // Public subnets + route tables
const RANK_NAT = 2; // NAT Gateways
const RANK_PRIVATE = 3; // Private subnets + route tables
const RANK_ENDPOINT = 4; // VPC Endpoints

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function rankForSubnet(s: Subnet): number {
  return s.type === "public" ? RANK_PUBLIC : RANK_PRIVATE;
}

/** Build a Set of route-table IDs that contain at least one blackhole */
function blackholeRtbIds(blackholes: BlackholeRoute[]): Set<string> {
  return new Set(blackholes.map((b) => b.route_table_id));
}

/** TGW attachments reference a transit_gateway_id, but route targets
 *  are the tgw-id. We need to map tgw-id → attachment node id. */
function buildTgwLookup(
  attachments: TransitGatewayAttachment[]
): Map<string, string> {
  const m = new Map<string, string>();
  for (const att of attachments) {
    m.set(att.transit_gateway_id, att.attachment_id);
  }
  return m;
}

/** Targets we recognise as gateway/peering/nat/endpoint node IDs */
const TARGET_PREFIXES = ["igw-", "nat-", "tgw-", "pcx-", "vpce-"] as const;

function isKnownTarget(target: string): boolean {
  return TARGET_PREFIXES.some((p) => target.startsWith(p));
}

/* ------------------------------------------------------------------ */
/*  Main mapping function                                              */
/* ------------------------------------------------------------------ */

export interface GraphData {
  nodes: Node<BaseNodeData>[];
  edges: Edge[];
}

export function mapTopologyToGraph(topo: VpcTopology): GraphData {
  const nodes: Node<BaseNodeData>[] = [];
  const edges: Edge[] = [];
  const bhSet = blackholeRtbIds(topo.blackhole_routes);
  const tgwLookup = buildTgwLookup(topo.transit_gateway_attachments);

  // Track which node IDs exist so we don't create edges to missing nodes
  const nodeIds = new Set<string>();

  /* ---------- Layer 0: External gateways ---------- */

  for (const igw of topo.internet_gateways) {
    nodeIds.add(igw.igw_id);
    nodes.push({
      id: igw.igw_id,
      type: "igwNode",
      position: { x: 0, y: 0 }, // dagre will override
      data: {
        label: igw.name ?? igw.igw_id,
        resourceType: "Internet Gateway",
        raw: igw as unknown as Record<string, unknown>,
      },
    });
  }

  for (const att of topo.transit_gateway_attachments) {
    nodeIds.add(att.attachment_id);
    nodes.push({
      id: att.attachment_id,
      type: "tgwNode",
      position: { x: 0, y: 0 },
      data: {
        label: att.transit_gateway_id,
        resourceType: "Transit Gateway",
        raw: att as unknown as Record<string, unknown>,
      },
    });
  }

  for (const pcx of topo.vpc_peering_connections) {
    nodeIds.add(pcx.pcx_id);
    nodes.push({
      id: pcx.pcx_id,
      type: "peeringNode",
      position: { x: 0, y: 0 },
      data: {
        label: pcx.pcx_id,
        resourceType: "VPC Peering",
        raw: pcx as unknown as Record<string, unknown>,
      },
    });
  }

  /* ---------- Layer 1-3: Subnets ---------- */

  for (const subnet of topo.subnets) {
    nodeIds.add(subnet.subnet_id);
    nodes.push({
      id: subnet.subnet_id,
      type: "subnetNode",
      position: { x: 0, y: 0 },
      data: {
        label: subnet.name ?? subnet.subnet_id,
        resourceType: subnet.type === "public" ? "Public Subnet" : "Private Subnet",
        raw: subnet as unknown as Record<string, unknown>,
      },
    });
  }

  /* ---------- Layer 2: NAT Gateways ---------- */

  for (const nat of topo.nat_gateways) {
    nodeIds.add(nat.nat_gateway_id);
    nodes.push({
      id: nat.nat_gateway_id,
      type: "natNode",
      position: { x: 0, y: 0 },
      data: {
        label: nat.name ?? nat.nat_gateway_id,
        resourceType: "NAT Gateway",
        raw: nat as unknown as Record<string, unknown>,
      },
    });

    // NAT → hosting subnet (dashed "hosted in")
    if (nat.subnet_id && nodeIds.has(nat.subnet_id)) {
      edges.push({
        id: `e-${nat.nat_gateway_id}-host-${nat.subnet_id}`,
        source: nat.nat_gateway_id,
        target: nat.subnet_id,
        type: "topologyEdge",
        data: { label: "hosted in", style: "dashed" },
      });
    }
  }

  /* ---------- Route Tables ---------- */

  // Collect route table IDs associated with subnets so we know which rank
  const subnetRtbRank = new Map<string, number>();
  for (const subnet of topo.subnets) {
    if (subnet.route_table_id) {
      // Use the lowest rank (public wins if shared)
      const current = subnetRtbRank.get(subnet.route_table_id);
      const rank = rankForSubnet(subnet);
      if (current === undefined || rank < current) {
        subnetRtbRank.set(subnet.route_table_id, rank);
      }
    }
  }

  for (const rtb of topo.route_tables) {
    const hasBh = bhSet.has(rtb.route_table_id);
    nodeIds.add(rtb.route_table_id);
    nodes.push({
      id: rtb.route_table_id,
      type: "routeTableNode",
      position: { x: 0, y: 0 },
      data: {
        label: rtb.name ?? rtb.route_table_id,
        resourceType: "Route Table",
        hasIssue: hasBh,
        raw: rtb as unknown as Record<string, unknown>,
      },
    });
  }

  /* ---------- Layer 4: VPC Endpoints ---------- */

  for (const vpce of topo.vpc_endpoints) {
    nodeIds.add(vpce.endpoint_id);
    nodes.push({
      id: vpce.endpoint_id,
      type: "endpointNode",
      position: { x: 0, y: 0 },
      data: {
        label: vpce.service_name.split(".").pop() ?? vpce.endpoint_id,
        resourceType: "VPC Endpoint",
        raw: vpce as unknown as Record<string, unknown>,
      },
    });

    // Endpoint → subnet edges
    for (const sid of vpce.subnet_ids) {
      if (nodeIds.has(sid)) {
        edges.push({
          id: `e-${vpce.endpoint_id}-sub-${sid}`,
          source: vpce.endpoint_id,
          target: sid,
          type: "topologyEdge",
          data: { label: "", style: "dotted" },
        });
      }
    }
  }

  /* ---------- Edges: Subnet → Route Table ---------- */

  for (const subnet of topo.subnets) {
    if (subnet.route_table_id && nodeIds.has(subnet.route_table_id)) {
      edges.push({
        id: `e-${subnet.subnet_id}-rtb-${subnet.route_table_id}`,
        source: subnet.subnet_id,
        target: subnet.route_table_id,
        type: "topologyEdge",
        data: { label: "", style: "solid" },
      });
    }
  }

  /* ---------- Edges: Route Table → target (IGW/NAT/TGW/PCX) ---------- */

  // Build a Set of blackhole (rtb_id, destination) pairs for quick lookup
  const bhEdges = new Set<string>();
  for (const bh of topo.blackhole_routes) {
    bhEdges.add(`${bh.route_table_id}:${bh.destination}`);
  }

  for (const rtb of topo.route_tables) {
    for (const route of rtb.routes) {
      // Skip "local" routes — they represent VPC-internal routing
      if (route.target === "local") continue;

      // Resolve TGW target: route target is tgw-xxx, node ID is the attachment ID
      let resolvedTarget = route.target;
      if (route.target.startsWith("tgw-")) {
        const attId = tgwLookup.get(route.target);
        if (attId) resolvedTarget = attId;
      }

      if (!nodeIds.has(resolvedTarget) && !isKnownTarget(route.target)) continue;
      if (!nodeIds.has(resolvedTarget)) continue;

      const isBlackhole =
        route.state === "blackhole" ||
        bhEdges.has(`${rtb.route_table_id}:${route.destination}`);

      edges.push({
        id: `e-${rtb.route_table_id}-route-${resolvedTarget}-${route.destination}`,
        source: rtb.route_table_id,
        target: resolvedTarget,
        type: "topologyEdge",
        data: {
          label: route.destination,
          style: isBlackhole ? "blackhole" : "solid",
        },
      });
    }
  }

  /* ---------- Deferred NAT edges (NAT node may be added after subnets) ---------- */
  // Re-check NAT hosted-in edges for nodes added after initial pass
  for (const nat of topo.nat_gateways) {
    const edgeId = `e-${nat.nat_gateway_id}-host-${nat.subnet_id}`;
    if (!edges.some((e) => e.id === edgeId) && nodeIds.has(nat.subnet_id)) {
      edges.push({
        id: edgeId,
        source: nat.nat_gateway_id,
        target: nat.subnet_id,
        type: "topologyEdge",
        data: { label: "hosted in", style: "dashed" },
      });
    }
  }

  /* ---------- Assign dagre rank metadata ---------- */

  for (const node of nodes) {
    switch (node.type) {
      case "igwNode":
      case "tgwNode":
      case "peeringNode":
        (node.data as BaseNodeData & { rank: number }).rank = RANK_EXTERNAL;
        break;
      case "subnetNode": {
        const raw = node.data.raw as unknown as Subnet;
        (node.data as BaseNodeData & { rank: number }).rank = rankForSubnet(raw);
        break;
      }
      case "natNode":
        (node.data as BaseNodeData & { rank: number }).rank = RANK_NAT;
        break;
      case "routeTableNode": {
        const rtbRank = subnetRtbRank.get(node.id) ?? RANK_PRIVATE;
        (node.data as BaseNodeData & { rank: number }).rank = rtbRank;
        break;
      }
      case "endpointNode":
        (node.data as BaseNodeData & { rank: number }).rank = RANK_ENDPOINT;
        break;
    }
  }

  return { nodes, edges };
}
