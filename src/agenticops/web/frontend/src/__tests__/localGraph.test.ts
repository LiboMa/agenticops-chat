import { describe, it, expect } from "vitest";
import type { FocusEdge, FocusNode, GraphFocus } from "@/api/types";
import { LOCAL_GRAPH_NODE_CAP, buildLocalGraph, focusPath } from "@/lib/localGraph";

function node(ref: number, hops: number, extra: Partial<FocusNode> = {}): FocusNode {
  return { ref, type: "EC2", name: `n-${ref}`, account_id: 1, region: "us-east-1", absent: false, hops,
           health: "unknown", issue_ids: [], anomalous: false, signal_at: null, ...extra };
}

function edge(src: number, dst: number, relation_type: string, provenance = "rule"): FocusEdge {
  return { src, dst, relation_type, provenance, evidence: "x", direction_label: "downstream",
           observed_at: "2026-09-28T01:02:03" };
}

function focus(extra: Partial<GraphFocus> = {}): GraphFocus {
  return {
    build_id: 1,
    // EC2(3) is the anchor; Subnet(2) contains it; SG(4) secures it; RDS(6) references it (llm)
    nodes: [node(3, 0, { health: "warning", issue_ids: [9] }), node(2, 1, { type: "Subnet" }),
            node(4, 1, { type: "SecurityGroup" }), node(6, 1, { type: "RDS" })],
    edges: [edge(2, 3, "contains"), edge(3, 4, "secured_by"), edge(3, 6, "references", "llm")],
    truncated: false, truncated_reason: null, depth: 1,
    anchor: { kind: "issue", id: 9, status: "anchored", rule: "resource_id", candidates: [], refs: [3] },
    blast: { structural: 5, potential: 2, observed: 1, truncated: false },
    window: { start: "2026-09-28T00:30:00", end: "2026-09-28T01:10:00" },
    related: { merged: [], candidates: [], truncated: false },
    ...extra,
  };
}

describe("focusPath", () => {
  it("asks for one subject, capped at the component's node limit", () => {
    expect(focusPath({ issueId: 9 })).toBe(`/graph/focus?issue_id=9&node_cap=${LOCAL_GRAPH_NODE_CAP}`);
    expect(focusPath({ changeRequestId: 4 })).toBe("/graph/focus?change_request_id=4&node_cap=200");
    expect(focusPath({ resourceId: 3 }, { includeLlm: true }))
      .toBe("/graph/focus?resource_id=3&node_cap=200&include_llm=true");
  });
});

describe("buildLocalGraph", () => {
  it("marks the anchor and draws rule edges; llm edges stay hidden until asked for", () => {
    const m = buildLocalGraph(focus());
    expect(m.anchorIds).toEqual(["r:3"]);
    expect(m.nodes.find((n) => n.id === "r:3")).toMatchObject({ anchor: true, health: "warning", issueIds: [9] });
    expect(m.links.map((l) => l.id)).toEqual(["s:2>3:contains", "s:3>4:secured_by"]);
    expect(m.hiddenLlm).toBe(1);
    const shown = buildLocalGraph(focus(), { showLlm: true });
    expect(shown.hiddenLlm).toBe(0);
    expect(shown.links.find((l) => l.id === "s:3>6:references")).toMatchObject({ llm: true, kind: "structural" });
  });

  it("drops an llm edge that twins a rule edge, drawn or not: one link per id, the twin never counted as hidden", () => {
    // the builder publishes an llm row next to the rule row for the same relation; the llm twin comes first here
    const edges = [edge(2, 3, "contains"), edge(3, 4, "secured_by", "llm"), edge(3, 4, "secured_by"),
                   edge(3, 6, "references", "llm")];
    expect(buildLocalGraph(focus({ edges })).hiddenLlm).toBe(1);
    const shown = buildLocalGraph(focus({ edges }), { showLlm: true });
    const ids = shown.links.map((l) => l.id);
    expect(ids).toEqual(["s:2>3:contains", "s:3>4:secured_by", "s:3>6:references"]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(shown.links.find((l) => l.id === "s:3>4:secured_by")).toMatchObject({ llm: false, provenance: "rule" });
    expect(shown.hiddenLlm).toBe(0);
  });

  it("highlights the RCA causal chain on its edges and nodes", () => {
    const m = buildLocalGraph(focus(), { path: [{ src_ref: 2, dst_ref: 3, relation_type: "contains" }] });
    expect(m.links.filter((l) => l.onPath).map((l) => l.id)).toEqual(["s:2>3:contains"]);
    expect(m.nodes.filter((n) => n.onPath).map((n) => n.id).sort()).toEqual(["r:2", "r:3"]);
  });

  it("links every merged-in resource to the issue: in the graph, outside it, or unanchored", () => {
    const merged = [
      { resource_id: "sg-1", ref: 4, type: "SecurityGroup", name: "sg-1", anchor_status: "anchored" as const,
        signals: 2, last_at: "2026-09-28T01:00:00" },
      { resource_id: "db-9", ref: 60, type: "RDS", name: "db-9", anchor_status: "anchored" as const,
        signals: 1, last_at: null },
      { resource_id: "ghost", ref: null, type: null, name: null, anchor_status: "unanchored" as const,
        signals: 1, last_at: null },
    ];
    const m = buildLocalGraph(focus({ related: { merged, candidates: [], truncated: false } }));
    const links = m.links.filter((l) => l.kind === "merged");
    expect(links.map((l) => [l.source, l.target])).toEqual([["r:4", "r:3"], ["m:db-9", "r:3"], ["m:ghost", "r:3"]]);
    expect(m.nodes.find((n) => n.id === "m:db-9")).toMatchObject({ kind: "merged", ref: 60, label: "db-9" });
    expect(m.nodes.find((n) => n.id === "m:ghost")).toMatchObject({ kind: "merged", ref: null, label: "ghost" });
    expect(m.nodes.find((n) => n.id === "r:4")!.merged).toEqual([merged[0]]);
  });

  it("an issue with no anchor still gets its merged signals, around the issue itself", () => {
    const m = buildLocalGraph(focus({
      nodes: [], edges: [],
      anchor: { kind: "issue", id: 9, status: "unanchored", rule: null, candidates: [], refs: [] },
      related: { merged: [{ resource_id: "db-9", ref: 60, type: "RDS", name: "db-9", anchor_status: "anchored",
                            signals: 1, last_at: null }], candidates: [], truncated: false },
    }));
    expect(m.anchorIds).toEqual(["i:9"]);
    expect(m.nodes.map((n) => [n.id, n.kind])).toEqual([["i:9", "issue"], ["m:db-9", "merged"]]);
    expect(m.links.map((l) => [l.source, l.target])).toEqual([["m:db-9", "i:9"]]);
    expect(buildLocalGraph(focus({ nodes: [], edges: [] })).nodes).toEqual([]);  // nothing to draw
  });

  it("marks candidate issues: on the anchor itself, on a drawn node, or on a resource outside the graph", () => {
    const c = (issue_id: number, ref: number, hops: number, severity = "high") =>
      ({ issue_id, ref, hops, severity, title: `t${issue_id}`, status: "open", signal_at: "2026-09-28T01:00:00" });
    const candidates = [c(10, 3, 0), c(11, 4, 1), c(12, 7, 2, "high"), c(13, 7, 2, "critical")];
    const m = buildLocalGraph(focus({ related: { merged: [], candidates, truncated: false } }));
    expect(m.nodes.find((n) => n.id === "r:3")!.candidates.map((x) => x.issue_id)).toEqual([10]);
    const links = m.links.filter((l) => l.kind === "candidate");
    expect(links.map((l) => [l.source, l.target])).toEqual([["r:3", "r:4"], ["r:3", "c:7"]]);
    expect(m.nodes.find((n) => n.id === "c:7")).toMatchObject({
      kind: "candidate", ref: 7, hops: 2, health: "critical", issueIds: [12, 13], label: "I#12, I#13" });
  });

  it("a resource outside the graph is one node, carrying every merged name and candidate issue on it", () => {
    // two merged names (short id and ARN) the identity resolver anchors to the same resource, plus a candidate on it
    const merged = [
      { resource_id: "db-9", ref: 60, type: "RDS", name: "db-9", anchor_status: "anchored" as const,
        signals: 1, last_at: null },
      { resource_id: "arn:db-9", ref: 60, type: "RDS", name: "db-9", anchor_status: "anchored" as const,
        signals: 2, last_at: null },
    ];
    const candidates = [{ issue_id: 12, ref: 60, hops: 2, severity: "critical", title: "t12", status: "open",
                          signal_at: "2026-09-28T01:00:00" }];
    const m = buildLocalGraph(focus({ related: { merged, candidates, truncated: false } }));
    expect(m.nodes.filter((n) => n.ref === 60).map((n) => n.id)).toEqual(["m:db-9"]);
    expect(m.nodes.find((n) => n.id === "m:db-9")).toMatchObject({
      kind: "merged", label: "db-9", hops: 2, health: "critical", issueIds: [12], merged, candidates });
    expect(m.links.filter((l) => l.kind !== "structural").map((l) => [l.id, l.source, l.target]))
      .toEqual([["m:db-9", "m:db-9", "r:3"], ["m:arn:db-9", "m:db-9", "r:3"], ["c:60", "r:3", "m:db-9"]]);
  });

  it("cuts a larger answer to the node limit, anchors kept and nearest first, and says so", () => {
    const many = [node(1, 2), ...Array.from({ length: 250 }, (_, i) => node(100 + i, 1)), node(3, 0)];
    const m = buildLocalGraph(focus({
      nodes: many, edges: [edge(3, 100, "contains"), edge(3, 349, "contains"), edge(1, 100, "contains")],
      anchor: { kind: "resource", id: 3, status: "anchored", rule: null, candidates: [], refs: [3] },
    }));
    expect(m.nodes).toHaveLength(LOCAL_GRAPH_NODE_CAP);
    expect(m.nodes.some((n) => n.id === "r:3")).toBe(true);
    expect(m.nodes.some((n) => n.id === "r:1")).toBe(false);          // farthest out: cut first
    expect(m.links.map((l) => l.id)).toEqual(["s:3>100:contains"]);   // never a link to a cut node
    expect(m.truncated).toEqual(["node_cap"]);
  });

  it("names every truncation: the API's reasons, then a capped related list", () => {
    const m = buildLocalGraph(focus({ truncated: true, truncated_reason: "expansion_cap+node_cap",
                                      related: { merged: [], candidates: [], truncated: true } }));
    expect(m.truncated).toEqual(["expansion_cap", "node_cap", "related"]);
  });
});
