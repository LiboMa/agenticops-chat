import { useMemo } from "react";
import Dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";
import type { BaseNodeData } from "./mapTopologyToGraph";

/* ------------------------------------------------------------------ */
/*  Node size defaults (pixels) — must match the actual rendered size  */
/* ------------------------------------------------------------------ */

const NODE_WIDTH = 200;
const NODE_HEIGHT = 60;
const ROUTE_TABLE_WIDTH = 160;
const ROUTE_TABLE_HEIGHT = 48;

function getNodeDimensions(type: string | undefined) {
  if (type === "routeTableNode") {
    return { width: ROUTE_TABLE_WIDTH, height: ROUTE_TABLE_HEIGHT };
  }
  return { width: NODE_WIDTH, height: NODE_HEIGHT };
}

/* ------------------------------------------------------------------ */
/*  Layout hook                                                        */
/* ------------------------------------------------------------------ */

interface LayoutResult {
  nodes: Node<BaseNodeData>[];
  edges: Edge[];
}

export function useAutoLayout(
  rawNodes: Node<BaseNodeData>[],
  rawEdges: Edge[]
): LayoutResult {
  return useMemo(() => {
    if (rawNodes.length === 0) return { nodes: [], edges: [] };

    const g = new Dagre.graphlib.Graph({ directed: true });
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: "TB",
      ranksep: 80,
      nodesep: 40,
      marginx: 20,
      marginy: 20,
    });

    // Add nodes
    for (const node of rawNodes) {
      const { width, height } = getNodeDimensions(node.type);
      g.setNode(node.id, { width, height });
    }

    // Add edges
    for (const edge of rawEdges) {
      g.setEdge(edge.source, edge.target);
    }

    // Assign ranks manually to enforce layer ordering
    for (const node of rawNodes) {
      const rank = (node.data as BaseNodeData & { rank?: number }).rank;
      if (rank !== undefined) {
        const dagreNode = g.node(node.id);
        if (dagreNode) {
          dagreNode.rank = rank;
        }
      }
    }

    Dagre.layout(g);

    // Map positions back to React Flow nodes (centered origin)
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
