import { useState, useCallback, useMemo } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { VpcTopology } from "@/api/types";
import { mapTopologyToGraph, type BaseNodeData } from "./mapTopologyToGraph";
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
  topology: VpcTopology;
}

export default function TopologyGraph({ topology }: TopologyGraphProps) {
  const [selectedNode, setSelectedNode] = useState<Node<BaseNodeData> | null>(null);

  // Map topology data → raw nodes/edges
  const { nodes: rawNodes, edges: rawEdges } = useMemo(
    () => mapTopologyToGraph(topology),
    [topology]
  );

  // Apply dagre layout
  const { nodes, edges } = useAutoLayout(rawNodes, rawEdges);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode(node as Node<BaseNodeData>);
    },
    []
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  return (
    <div className="relative w-full h-[600px] bg-gray-50 rounded-lg border border-gray-200">
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
        {/* Arrow marker definition for edges */}
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
    </div>
  );
}
