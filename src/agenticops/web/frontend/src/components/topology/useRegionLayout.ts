import { useMemo } from "react";
import Dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";
import type { RegionNodeData } from "./types";

const VPC_WIDTH = 240;
const VPC_HEIGHT = 80;
const TGW_WIDTH = 240;
const TGW_HEIGHT = 80;

function getNodeDimensions(type: string | undefined) {
  if (type === "tgwHubNode") return { width: TGW_WIDTH, height: TGW_HEIGHT };
  return { width: VPC_WIDTH, height: VPC_HEIGHT };
}

interface LayoutResult {
  nodes: Node<RegionNodeData>[];
  edges: Edge[];
}

export function useRegionLayout(
  rawNodes: Node<RegionNodeData>[],
  rawEdges: Edge[],
): LayoutResult {
  return useMemo(() => {
    if (rawNodes.length === 0) return { nodes: [], edges: [] };

    const g = new Dagre.graphlib.Graph({ directed: false });
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "TB",
      ranksep: 120,
      nodesep: 80,
      marginx: 40,
      marginy: 40,
    });

    for (const node of rawNodes) {
      const { width, height } = getNodeDimensions(node.type);
      g.setNode(node.id, { width, height });
    }

    for (const edge of rawEdges) {
      g.setEdge(edge.source, edge.target);
    }

    // TGWs at top, VPCs at bottom
    for (const node of rawNodes) {
      if (node.type === "tgwHubNode") {
        const n = g.node(node.id);
        if (n) n.rank = 0;
      } else {
        const n = g.node(node.id);
        if (n) n.rank = 1;
      }
    }

    Dagre.layout(g);

    const layoutNodes = rawNodes.map((node) => {
      const pos = g.node(node.id);
      const { width, height } = getNodeDimensions(node.type);
      return {
        ...node,
        position: {
          x: pos.x - width / 2,
          y: pos.y - height / 2,
        },
      };
    });

    return { nodes: layoutNodes, edges: rawEdges };
  }, [rawNodes, rawEdges]);
}
