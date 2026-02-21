import { useCallback, useMemo } from "react";
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

import type { SerializedGraph } from "@/api/types";
import type { RegionNodeData } from "./types";
import { useRegionLayout } from "./useRegionLayout";

// Custom node types
import { VpcGroupNode } from "./nodes/VpcGroupNode";
import { TgwHubNode } from "./nodes/TgwHubNode";

// Reuse existing edge component
import { TopologyEdge } from "./edges/TopologyEdge";

/* ------------------------------------------------------------------ */
/*  Type registrations                                                 */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  vpcGroupNode: VpcGroupNode,
  tgwHubNode: TgwHubNode,
} as const;

const edgeTypes = {
  topologyEdge: TopologyEdge,
} as const;

/* ------------------------------------------------------------------ */
/*  MiniMap colors                                                     */
/* ------------------------------------------------------------------ */

function miniMapColor(node: Node): string {
  switch (node.type) {
    case "vpcGroupNode": {
      const d = node.data as Record<string, unknown>;
      return d.state === "external" ? "#d1d5db" : "#34d399";
    }
    case "tgwHubNode":
      return "#c084fc";
    default:
      return "#e5e7eb";
  }
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface RegionTopologyGraphProps {
  /** Pre-serialized graph from the backend graph API */
  graph: SerializedGraph;
  onVpcClick?: (vpcId: string) => void;
}

export default function RegionTopologyGraph({
  graph,
  onVpcClick,
}: RegionTopologyGraphProps) {
  // Convert backend SerializedGraph -> ReactFlow nodes/edges
  const rawNodes: Node<RegionNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data as RegionNodeData,
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
  const { nodes, edges } = useRegionLayout(rawNodes, rawEdges);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (node.type === "vpcGroupNode" && onVpcClick) {
        const d = node.data as Record<string, unknown>;
        const vpcId = d.vpcId as string | undefined;
        if (vpcId && d.state !== "external") {
          onVpcClick(vpcId);
        }
      }
    },
    [onVpcClick],
  );

  return (
    <div className="relative w-full h-[500px] bg-gray-50 rounded-lg border border-gray-200">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
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

      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-white/90 border border-gray-200 rounded-md px-3 py-2 text-[10px] text-gray-500 flex gap-4">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-emerald-200 border border-emerald-400 inline-block" />
          VPC
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-purple-200 border border-purple-400 inline-block" />
          Transit GW
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-gray-100 border-dashed border border-gray-300 inline-block" />
          External VPC
        </span>
        <span className="text-gray-400">Click VPC to drill in</span>
      </div>
    </div>
  );
}
