/**
 * View model of the local graph (MVP-2.6.1 spec §3.E.3): a GET /api/graph/focus answer → the nodes and links
 * LocalGraph.tsx lays out with d3-force, and the list view that stands in for the drawing.
 *
 * Four kinds of line: structural relations (rule solid, llm dashed and hidden by default), the RCA causal
 * chain (highlighted structural edges), merged signals (resources the Signal Gate merged into the issue) and
 * candidate links (other open issues within 2 hops in the window — computed by the API, never stored).
 * The blast-radius numbers are the API's own; nothing here counts them.
 */
import type { FocusCandidate, FocusMerged, GalaxyHealth, GraphFocus, LocationPathEdge } from "@/api/types";
import { HEALTH_VALUES, normalizeHealth } from "@/lib/galaxyHealth";

export const LOCAL_GRAPH_NODE_CAP = 200;

export type FocusSubject = { issueId: number } | { resourceId: number } | { changeRequestId: number };

export function focusPath(subject: FocusSubject, opts: { includeLlm?: boolean } = {}): string {
  const [key, id] = "issueId" in subject ? ["issue_id", subject.issueId]
    : "resourceId" in subject ? ["resource_id", subject.resourceId]
    : ["change_request_id", subject.changeRequestId];
  return `/graph/focus?${key}=${id}&node_cap=${LOCAL_GRAPH_NODE_CAP}${opts.includeLlm ? "&include_llm=true" : ""}`;
}

// "r:<ref>" a resource the API drew; "m:<resource_id>" a merged-in resource outside it; "c:<ref>" a
// candidate issue's resource outside it, not merged-in; "i:<id>" the issue itself when it has no anchor to stand on.
export interface LgNode {
  id: string;
  kind: "resource" | "merged" | "candidate" | "issue";
  ref: number | null;
  label: string;
  type: string | null;
  hops: number | null;
  health: GalaxyHealth;
  issueIds: number[]; // open issues on it — the API counts only OPEN_ISSUE_STATUSES
  anchor: boolean;
  onPath: boolean;
  absent: boolean;
  merged: FocusMerged[];
  candidates: FocusCandidate[];
}

export interface LgLink {
  id: string;
  kind: "structural" | "merged" | "candidate";
  source: string;
  target: string;
  llm: boolean;
  onPath: boolean;
  relationType?: string;
  provenance?: string;
  evidence?: string;
  observedAt?: string | null;
  merged?: FocusMerged;
  candidates?: FocusCandidate[];
}

export interface LocalGraphModel {
  nodes: LgNode[];
  links: LgLink[];
  anchorIds: string[];
  truncated: string[]; // expansion_cap / node_cap / edge_cap (the API's, in order), then "related"
}

// Mirrors graph/query_service._SEVERITY_HEALTH
const SEVERITY_HEALTH: Record<string, GalaxyHealth> = { critical: "critical", high: "warning" };

function worst(a: GalaxyHealth, b: GalaxyHealth): GalaxyHealth {
  return HEALTH_VALUES.indexOf(b) > HEALTH_VALUES.indexOf(a) ? b : a;
}

function blank(id: string, kind: LgNode["kind"], label: string): LgNode {
  return { id, kind, ref: null, label, type: null, hops: null, health: "unknown", issueIds: [], anchor: false,
           onPath: false, absent: false, merged: [], candidates: [] };
}

export function buildLocalGraph(focus: GraphFocus,
                                opts: { showLlm?: boolean; path?: LocationPathEdge[] } = {}): LocalGraphModel {
  const anchorRefs = new Set(focus.anchor.refs ?? []);
  const pathKeys = new Set((opts.path ?? []).map((e) => `${e.src_ref}>${e.dst_ref}:${e.relation_type}`));
  const pathRefs = new Set((opts.path ?? []).flatMap((e) => [e.src_ref, e.dst_ref]));
  const truncated = (focus.truncated_reason ?? "").split("+").filter(Boolean);

  // node_cap applies per start, so a change request's union can exceed it: anchors first, then nearest
  const ordered = [...focus.nodes].sort((a, b) =>
    Number(anchorRefs.has(b.ref)) - Number(anchorRefs.has(a.ref)) || a.hops - b.hops || a.ref - b.ref);
  if (ordered.length > LOCAL_GRAPH_NODE_CAP && !truncated.includes("node_cap")) truncated.push("node_cap");
  const nodes = new Map<string, LgNode>();
  for (const n of ordered.slice(0, LOCAL_GRAPH_NODE_CAP)) {
    nodes.set(`r:${n.ref}`, {
      ...blank(`r:${n.ref}`, "resource", n.name || `#${n.ref}`), ref: n.ref, type: n.type, hops: n.hops,
      health: normalizeHealth(n.health), issueIds: n.issue_ids, anchor: anchorRefs.has(n.ref),
      onPath: pathRefs.has(n.ref), absent: n.absent,
    });
  }

  // An llm edge that twins a rule edge (same src, dst and type) adds nothing: the rule layer wins
  const edgeKey = (e: { src: number; dst: number; relation_type: string }) => `${e.src}>${e.dst}:${e.relation_type}`;
  const ruleKeys = new Set(focus.edges.filter((e) => e.provenance !== "llm").map(edgeKey));
  const links: LgLink[] = [];
  for (const e of focus.edges) {
    const llm = e.provenance === "llm";
    const key = edgeKey(e);
    if (llm && ruleKeys.has(key)) continue;
    if (llm && !opts.showLlm) continue;
    if (!nodes.has(`r:${e.src}`) || !nodes.has(`r:${e.dst}`)) continue;
    links.push({ id: `s:${key}`, kind: "structural", source: `r:${e.src}`, target: `r:${e.dst}`, llm,
                 onPath: pathKeys.has(key), relationType: e.relation_type, provenance: e.provenance,
                 evidence: e.evidence, observedAt: e.observed_at });
  }

  const anchorIds = [...nodes.values()].filter((n) => n.anchor).map((n) => n.id);
  const { merged, candidates } = focus.related;
  if (!anchorIds.length && focus.anchor.kind === "issue" && merged.length) {
    const hub = { ...blank(`i:${focus.anchor.id}`, "issue", `I#${focus.anchor.id}`), anchor: true };
    nodes.set(hub.id, hub);
    anchorIds.push(hub.id);
  }
  const hub = anchorIds[0];

  const outside = new Map<number, LgNode>(); // a resource outside the graph is one node, merged-in or a candidate's
  for (const m of merged) {
    let n = m.ref != null ? nodes.get(`r:${m.ref}`) ?? outside.get(m.ref) : undefined;
    if (!n) {
      n = { ...blank(`m:${m.resource_id}`, "merged", m.name || m.resource_id), ref: m.ref, type: m.type };
      nodes.set(n.id, n);
      if (m.ref != null) outside.set(m.ref, n);
    }
    n.merged.push(m);
    if (hub && n.id !== hub) {
      links.push({ id: `m:${m.resource_id}`, kind: "merged", source: n.id, target: hub, llm: false, onPath: false,
                   merged: m });
    }
  }

  const byRef = new Map<number, FocusCandidate[]>();
  for (const c of candidates) byRef.set(c.ref, [...(byRef.get(c.ref) ?? []), c]);
  for (const [ref, cs] of byRef) {
    let n = nodes.get(`r:${ref}`) ?? outside.get(ref);
    if (!n) {
      n = { ...blank(`c:${ref}`, "candidate", cs.map((c) => `I#${c.issue_id}`).join(", ")), ref };
      nodes.set(n.id, n);
    }
    if (n.kind !== "resource") { // outside the graph the API sent no state for it: its candidate issues are that
      n.hops = cs[0].hops;
      n.issueIds = cs.map((c) => c.issue_id);
      n.health = cs.reduce((h, c) => worst(h, SEVERITY_HEALTH[c.severity?.toLowerCase()] ?? "notice"), n.health);
    }
    n.candidates.push(...cs);
    if (hub && n.id !== hub) {
      links.push({ id: `c:${ref}`, kind: "candidate", source: hub, target: n.id, llm: false, onPath: false,
                   candidates: cs });
    }
  }

  if (focus.related.truncated) truncated.push("related");
  return { nodes: [...nodes.values()], links, anchorIds, truncated };
}

/** The default drawing on an issue page (P11): the anchor, the RCA causal path, merged signals, then the
 *  anchor's 1-hop neighbours and candidate issues — capped, so a 132-neighbour star stays readable. */
export const COMPACT_NODE_CAP = 15;

function compactRank(nd: LgNode): number {
  if (nd.anchor) return 0;
  if (nd.onPath) return 1;
  if (nd.kind === "merged" || nd.kind === "issue") return 2;
  if (nd.kind === "resource" && (nd.hops ?? Infinity) <= 1) return 3;
  if (nd.kind === "candidate") return 4;
  return 9;
}

export function compactLocalGraph(model: LocalGraphModel, cap = COMPACT_NODE_CAP): { model: LocalGraphModel; hidden: number } {
  const ranked = model.nodes
    .map((nd, i) => ({ nd, i, r: compactRank(nd) }))
    .filter((x) => x.r < 9)
    .sort((a, b) => a.r - b.r || (a.nd.hops ?? Infinity) - (b.nd.hops ?? Infinity) || a.i - b.i);
  const kept = new Set(ranked.slice(0, cap).map((x) => x.nd.id));
  if (kept.size === model.nodes.length) return { model, hidden: 0 };
  const nodes = model.nodes.filter((nd) => kept.has(nd.id));
  return {
    model: { ...model, nodes, links: model.links.filter((l) => kept.has(l.source) && kept.has(l.target)),
             anchorIds: model.anchorIds.filter((id) => kept.has(id)) },
    hidden: model.nodes.length - nodes.length,
  };
}
