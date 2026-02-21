import { useState, useCallback, useMemo } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { SerializedGraph, ReachabilityResult } from "@/api/types";
import type { BaseNodeData } from "./types";
import { useAutoLayout } from "./useAutoLayout";
import { NodeDetailPanel } from "./NodeDetailPanel";

// Custom node types
import { SubnetNode } from "./nodes/SubnetNode";
import { IGWNode } from "./nodes/IGWNode";
import { NATNode } from "./nodes/NATNode";
import { TGWNode } from "./nodes/TGWNode";
import { PeeringNode } from "./nodes/PeeringNode";
import { EndpointNode } from "./nodes/EndpointNode";
import { RouteTableNode } from "./nodes/RouteTableNode";

// Custom edge types
import { TopologyEdge } from "./edges/TopologyEdge";

/* ------------------------------------------------------------------ */
/*  Type registrations                                                 */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  subnetNode: SubnetNode,
  igwNode: IGWNode,
  natNode: NATNode,
  tgwNode: TGWNode,
  peeringNode: PeeringNode,
  endpointNode: EndpointNode,
  routeTableNode: RouteTableNode,
} as const;

const edgeTypes = {
  topologyEdge: TopologyEdge,
} as const;

/* ------------------------------------------------------------------ */
/*  MiniMap color mapping                                              */
/* ------------------------------------------------------------------ */

function miniMapColor(node: Node): string {
  switch (node.type) {
    case "igwNode":
      return "#60a5fa";
    case "tgwNode":
      return "#c084fc";
    case "peeringNode":
      return "#2dd4bf";
    case "subnetNode": {
      const raw = (node.data as BaseNodeData).raw as { type?: string };
      return raw.type === "public" ? "#4ade80" : "#9ca3af";
    }
    case "natNode":
      return "#fb923c";
    case "endpointNode":
      return "#818cf8";
    case "routeTableNode":
      return "#94a3b8";
    default:
      return "#e5e7eb";
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface TopologyGraphProps {
  /** Pre-serialized graph from the backend graph API */
  graph: SerializedGraph;
  /** Reachability result to highlight a path (optional) */
  reachability?: ReachabilityResult | null;
  /** Callback when a subnet node is clicked */
  onSubnetClick?: (subnetId: string) => void;
}

export default function TopologyGraph({
  graph,
  reachability,
  onSubnetClick,
}: TopologyGraphProps) {
  const [selectedNode, setSelectedNode] = useState<Node<BaseNodeData> | null>(null);

  // Convert backend SerializedGraph -> ReactFlow nodes/edges
  const rawNodes: Node<BaseNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data as BaseNodeData,
      })),
    [graph.nodes],
  );

  const rawEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: e.type,
        data: e.data,
      })),
    [graph.edges],
  );

  // Apply dagre layout
  const { nodes: layoutNodes, edges: layoutEdges } = useAutoLayout(rawNodes, rawEdges);

  // Build path highlight from reachability result
  const highlightedNodeIds = useMemo(() => {
    if (!reachability?.path?.length) return new Set<string>();
    return new Set(reachability.path);
  }, [reachability]);

  const highlightedEdgeIds = useMemo(() => {
    if (!reachability?.path?.length) return new Set<string>();
    const ids = new Set<string>();
    const pathNodes = reachability.path;
    for (let i = 0; i < pathNodes.length - 1; i++) {
      for (const edge of layoutEdges) {
        if (
          (edge.source === pathNodes[i] && edge.target === pathNodes[i + 1]) ||
          (edge.source === pathNodes[i + 1] && edge.target === pathNodes[i])
        ) {
          ids.add(edge.id);
        }
      }
    }
    return ids;
  }, [reachability, layoutEdges]);

  const hasHighlight = highlightedNodeIds.size > 0;

  // Apply highlight/dim to nodes
  const nodes = useMemo(() => {
    if (!hasHighlight) return layoutNodes;
    return layoutNodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        highlighted: highlightedNodeIds.has(node.id),
        dimmed: !highlightedNodeIds.has(node.id),
      },
    }));
  }, [layoutNodes, hasHighlight, highlightedNodeIds]);

  // Apply highlight to edges
  const edges = useMemo(() => {
    if (!hasHighlight) return layoutEdges;
    return layoutEdges.map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        highlighted: highlightedEdgeIds.has(edge.id),
      },
    }));
  }, [layoutEdges, hasHighlight, highlightedEdgeIds]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode(node as Node<BaseNodeData>);
      if (node.type === "subnetNode" && onSubnetClick) {
        onSubnetClick(node.id);
      }
    },
    [onSubnetClick],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  return (
    <div className="relative w-full h-[700px] bg-gray-50 rounded-lg border border-gray-200">
      {/* Blackhole animation keyframes */}
      <style>{`
        @keyframes blackhole-flow {
          0% { stroke-dashoffset: 24; }
          100% { stroke-dashoffset: 0; }
        }
      `}</style>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        {/* Arrow marker definitions for edges */}
        <svg>
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerUnits="strokeWidth"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af" />
            </marker>
            <marker
              id="arrow-highlighted"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerUnits="strokeWidth"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#4ade80" />
            </marker>
          </defs>
        </svg>

        <Controls
          showInteractive={false}
          className="!bg-white !border-gray-200 !shadow-sm"
        />
        <MiniMap
          nodeColor={miniMapColor}
          maskColor="rgba(0,0,0,0.08)"
          className="!bg-white !border-gray-200"
        />
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e5e7eb" />
      </ReactFlow>

      <NodeDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />

      {/* Reachability indicator */}
      {reachability && (
        <div
          className={`absolute top-3 left-3 px-3 py-2 rounded-md text-xs font-medium ${
            reachability.can_reach_internet
              ? "bg-green-100 text-green-800 border border-green-300"
              : "bg-red-100 text-red-800 border border-red-300"
          }`}
        >
          {reachability.can_reach_internet
            ? `Subnet can reach Internet (${reachability.path.length} hops)`
            : `No Internet access: ${reachability.blocking_reason}`}
        </div>
      )}
    </div>
  );
}
