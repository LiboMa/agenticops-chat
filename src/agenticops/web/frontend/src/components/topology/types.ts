/**
 * Shared type definitions for topology graph components.
 *
 * Previously split across mapTopologyToGraph.ts and mapRegionTopologyToGraph.ts,
 * now centralized here since graph mapping is done server-side.
 */

/* ------------------------------------------------------------------ */
/*  Node status                                                        */
/* ------------------------------------------------------------------ */

export type NodeStatus = "healthy" | "warning" | "error" | "unknown";

/* ------------------------------------------------------------------ */
/*  Base data shape shared by all VPC-level custom nodes              */
/* ------------------------------------------------------------------ */

export interface BaseNodeData extends Record<string, unknown> {
  label: string;
  resourceType: string;
  /** Raw AWS resource object for the detail panel */
  raw: Record<string, unknown>;
  /** Whether this node has an issue (blackhole, etc.) */
  hasIssue?: boolean;
  /** Path-highlight support */
  highlighted?: boolean;
  /** Dimmed when highlight is active and node is not on the path */
  dimmed?: boolean;
  /** Runtime health status */
  status?: NodeStatus;
  /** Dagre rank (layer) */
  rank?: number;
}

/* ------------------------------------------------------------------ */
/*  Region-level node data shapes                                      */
/* ------------------------------------------------------------------ */

export interface VpcNodeData extends Record<string, unknown> {
  label: string;
  resourceType: "VPC";
  vpcId: string;
  cidr: string;
  subnetCount: number;
  isDefault: boolean;
  state: string;
}

export interface TgwNodeData extends Record<string, unknown> {
  label: string;
  resourceType: "Transit Gateway";
  tgwId: string;
  state: string;
  attachmentCount: number;
}

export interface PeeringEdgeNodeData extends Record<string, unknown> {
  label: string;
  resourceType: "VPC Peering";
  pcxId: string;
  status: string;
}

export type RegionNodeData = VpcNodeData | TgwNodeData | PeeringEdgeNodeData;
