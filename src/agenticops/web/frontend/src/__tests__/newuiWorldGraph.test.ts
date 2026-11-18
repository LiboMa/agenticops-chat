import { describe, expect, it } from "vitest";
import type { GalaxyGraph, GalaxyGraphEdge, GalaxyGraphNode } from "@/api/types";
import { applyHealth, indexGraph } from "@/newui/lib/world/graph";

const res = (ref: number, type: string, over: Partial<GalaxyGraphNode> = {}): GalaxyGraphNode =>
  ({ id: `res:${ref}`, kind: "resource", name: `${type.toLowerCase()}-${ref}`, type, acct: 1, health: "unknown", absent: false, ...over });
const edge = (s: string, t: string, r: string, p: "rule" | "llm" = "rule"): GalaxyGraphEdge => ({ s, t, r, p });

/** One account: a VPC with a subnet and a security group, an instance in the subnet secured by the group, a database
 *  in two subnets, a role the account holds directly, a tag group, and one relation a model inferred. */
const payload: GalaxyGraph = {
  build_id: 172,
  nodes: [
    { id: "acct:1", kind: "account", name: "prod", type: "" },
    { id: "grp:1:project:shop", kind: "group", name: "shop", type: "project", acct: 1, members: 2 },
    res(30, "EC2", { health: "critical" }), res(10, "VPC"), res(21, "Subnet"), res(20, "Subnet"), res(40, "SecurityGroup"),
    res(50, "RDS", { health: "warning" }), res(60, "IAMRole", { absent: true, health: "notice" }),
  ],
  edges: [
    edge("acct:1", "res:10", "contains"), edge("acct:1", "res:60", "contains"),
    edge("res:10", "res:20", "contains"), edge("res:10", "res:21", "contains"), edge("res:10", "res:40", "contains"),
    edge("res:20", "res:30", "contains"), edge("res:21", "res:50", "contains"), edge("res:20", "res:50", "contains"),
    edge("res:30", "res:40", "secured_by"), edge("res:30", "grp:1:project:shop", "member_of"), edge("res:50", "grp:1:project:shop", "member_of"),
    { ...edge("res:30", "res:60", "references", "llm"), ev: "instance profile names the role", c: 0.8 },
  ],
};

describe("indexGraph — the relation graph as the map draws it", () => {
  const g = indexGraph(payload);
  const at = (ref: number) => g.nodes[g.byId.get(`res:${ref}`)!];

  it("draws resources, in a fixed order — accounts and tag groups are not dots", () => {
    expect(g.nodes.map((n) => n.ref)).toEqual([10, 20, 21, 30, 40, 50, 60]);
    expect(g.nodes.map((n) => n.i)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(g.buildId).toBe(172);
  });

  it("keeps each resource's account, and the groups it belongs to", () => {
    expect(g.accounts).toEqual([{ id: 1, name: "prod", count: 7 }]);
    expect(at(30).groups).toEqual(["grp:1:project:shop"]);
    expect(at(10).groups).toEqual([]);
    expect(g.groups).toEqual([{ id: "grp:1:project:shop", name: "shop", type: "project", acct: 1, count: 2 }]);
  });

  it("takes the accounts' real names when it is given them — the build only knows «account:1»", () => {
    const named = indexGraph(payload, new Map([[1, "Production CN"]]));
    expect(named.accounts).toEqual([{ id: 1, name: "Production CN", count: 7 }]);
    expect(indexGraph(payload, new Map([[2, "other"]])).accounts[0].name).toBe("prod");       // no name given for it: the build's
  });

  it("gives every resource one container: the resource that holds it — the lowest id when several do", () => {
    expect(at(30).parent).toBe(at(20).i);
    expect(at(50).parent).toBe(at(20).i);          // in subnets 20 and 21: always 20
    expect(at(20).parent).toBe(at(10).i);
    expect(at(10).parent).toBe(-1);                // held by the account only
    expect(at(60).parent).toBe(-1);
  });

  it("keeps the links between resources, and says which are containment and which a model inferred", () => {
    const show = g.edges.map((e) => `${g.nodes[e.a].ref}>${g.nodes[e.b].ref} ${e.r}${e.contain ? " [contain]" : ""}${e.llm ? " [llm]" : ""}`);
    expect(show).toEqual([
      "10>20 contains [contain]", "10>21 contains [contain]", "10>40 contains [contain]", "20>30 contains [contain]",
      "21>50 contains [contain]", "20>50 contains [contain]", "30>40 secured_by", "30>60 references [llm]",
    ]);
    expect(g.edges[7]).toMatchObject({ ev: "instance profile names the role", c: 0.8 });
  });

  it("accounts for every relation of the build: drawn as a line, shown as a cluster, or kept as a label / a filter", () => {
    expect(g.totals).toEqual({
      nodes: 7, present: 6, gone: 1,
      relations: 12,            // everything the build has
      links: 8,                 // between two resources
      lines: 2,                 // drawn as a line on the flat map: not containment
      contain: 6, rule: 7, inferred: 1,
      containExtra: 1,          // containment not drawn as a circle: the database's second subnet
      ofAccount: 2,             // an account holding a resource: the region label
      ofGroup: 2,               // a resource in a tag group: the group filter
      dropped: 0,
    });
    expect(g.totals.links + g.totals.ofAccount + g.totals.ofGroup + g.totals.dropped).toBe(g.totals.relations);
  });

  it("knows who is linked to whom, and in which direction the link is written", () => {
    const nb = g.adj[at(30).i].map(([j, e, out]) => `${g.nodes[j].ref}:${g.edges[e].r}:${out ? "out" : "in"}`).sort();
    expect(nb).toEqual(["20:contains:in", "40:secured_by:out", "60:references:out"]);
  });

  it("counts a relation whose end is not in the build as dropped, and draws nothing for it", () => {
    const broken = indexGraph({ ...payload, edges: [...payload.edges, edge("res:30", "res:999", "uses"), edge("grp:x", "acct:1", "odd")] });
    expect(broken.totals.dropped).toBe(2);
    expect(broken.totals.links).toBe(8);
    expect(broken.totals.links + broken.totals.ofAccount + broken.totals.ofGroup + broken.totals.dropped).toBe(broken.totals.relations);
  });

  it("reads a health it does not know as unknown — never as healthy", () => {
    const odd = indexGraph({ ...payload, nodes: [res(1, "EC2", { health: "great" as never }), res(2, "EC2", { health: undefined })] , edges: [] });
    expect(odd.nodes.map((n) => n.health)).toEqual(["unknown", "unknown"]);
  });

  it("is empty for a build with nothing in it", () => {
    const none = indexGraph({ nodes: [], edges: [], build_id: null });
    expect([none.nodes.length, none.edges.length, none.buildId, none.totals.relations]).toEqual([0, 0, null, 0]);
  });
});

describe("what the map can say about its own age and its circles", () => {
  it("carries when its build finished and when health was read — two different times", () => {
    const g = indexGraph({ ...payload, built_at: "2026-11-11T18:01:56Z", health_at: "2026-11-17T09:00:00Z" });
    expect([g.builtAt, g.healthAt]).toEqual(["2026-11-11T18:01:56Z", "2026-11-17T09:00:00Z"]);
    expect([indexGraph(payload).builtAt, indexGraph(payload).healthAt]).toEqual([null, null]);       // an older server says neither
  });

  it("counts the containment that is not drawn as a circle: a resource in several holders sits in one", () => {
    // the database is in two subnets; it is drawn inside the one with the lowest id, the other relation is a line when it is open
    const t = indexGraph(payload).totals;
    expect([t.contain, t.containExtra]).toEqual([6, 1]);
  });
});

describe("applyHealth — health and «gone» read again, on the same graph", () => {
  // the rings must follow the issues, not wait for the next build; the graph object stays the same one, so the map
  // keeps its layout and the camera does not move
  it("replaces every resource's health and «gone» by what was read now, and says whether anything changed", () => {
    const g = indexGraph({ ...payload, health_at: "2026-11-17T09:00:00Z" });
    const node = (ref: number) => g.nodes[g.byId.get(`res:${ref}`)!];
    const read = { build_id: 172, at: "2026-11-17T09:45:00Z", health: { "res:30": "notice", "res:20": "critical" }, absent: ["res:40"] };
    expect(applyHealth(g, read)).toBe(true);
    expect([node(30).health, node(20).health, node(50).health]).toEqual(["notice", "critical", "unknown"]);     // not listed = no open issue
    expect([node(40).absent, node(60).absent]).toEqual([true, false]);                                          // a resource that was gone is back
    expect([g.totals.gone, g.totals.present, g.healthAt]).toEqual([1, 6, "2026-11-17T09:45:00Z"]);
    expect(applyHealth(g, { ...read, at: "2026-11-17T09:46:00Z" })).toBe(false);                                // nothing changed …
    expect(g.healthAt).toBe("2026-11-17T09:46:00Z");                                                            // … but it is as of now
  });

  it("a reading of a past moment is marked as that, and a reading of now clears the mark (N15)", () => {
    const g = indexGraph({ ...payload, health_at: "2026-11-17T09:00:00Z" });
    expect(g.asOf).toBeNull();
    const past = { build_id: 172, at: "2026-11-17T09:45:00Z", as_of: "2026-11-17T03:00:00Z", health: { "res:20": "warning" }, absent: [] };
    expect(applyHealth(g, past)).toBe(true);
    expect([g.asOf, g.healthAt]).toEqual(["2026-11-17T03:00:00Z", "2026-11-17T09:45:00Z"]);
    applyHealth(g, { build_id: 172, at: "2026-11-17T09:46:00Z", health: {}, absent: [] });
    expect(g.asOf).toBeNull();
  });

  it("does nothing with a reading of another build", () => {
    const g = indexGraph({ ...payload, health_at: "2026-11-17T09:00:00Z" });
    expect(applyHealth(g, { build_id: 173, at: "2026-11-17T09:45:00Z", health: {}, absent: [] })).toBe(false);
    expect([g.healthAt, g.totals.gone]).toEqual(["2026-11-17T09:00:00Z", 1]);
  });
});

