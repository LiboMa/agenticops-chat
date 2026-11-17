import { describe, expect, it } from "vitest";
import type { GalaxyGraph, GalaxyGraphEdge, GalaxyGraphNode } from "@/api/types";
import { indexGraph } from "@/newui/lib/world/graph";
import { NO_ASK, around, confirm, expected, hopMarks, path, reconcile, scene, search, type Ask, type Drawn } from "@/newui/lib/world/scene";

const res = (ref: number, type: string, over: Partial<GalaxyGraphNode> = {}): GalaxyGraphNode =>
  ({ id: `res:${ref}`, kind: "resource", name: `${type.toLowerCase()}-${ref}`, type, acct: 1, health: "unknown", absent: false, ...over });
const edge = (s: number | string, t: number | string, r: string, p: "rule" | "llm" = "rule"): GalaxyGraphEdge =>
  ({ s: typeof s === "number" ? `res:${s}` : s, t: typeof t === "number" ? `res:${t}` : t, r, p });

/** Account 1: VPC 10 holds subnets 20, 21 and group 40; subnet 20 holds instances 30 (critical) and 31; subnet 21 holds
 *  database 50 (warning); 30 and 50 are secured by 40; role 60 is gone but still has an open issue; bucket 70 has a
 *  notice. Account 2: a lone function 80, which a model thinks refers to bucket 70. */
const payload: GalaxyGraph = {
  build_id: 9,
  nodes: [
    { id: "acct:1", kind: "account", name: "prod", type: "" }, { id: "acct:2", kind: "account", name: "dev", type: "" },
    { id: "grp:1:project:shop", kind: "group", name: "shop", type: "project", acct: 1, members: 2 },
    res(10, "VPC"), res(20, "Subnet"), res(21, "Subnet"), res(30, "EC2", { health: "critical", name: "web-1" }), res(31, "EC2", { name: "web-2" }),
    res(40, "SecurityGroup"), res(50, "RDS", { health: "warning", name: "orders-db" }), res(60, "IAMRole", { absent: true, health: "notice" }),
    res(70, "S3", { health: "notice", name: "logs" }), res(80, "Lambda", { acct: 2, name: "resize" }),
  ],
  edges: [
    edge("acct:1", 10, "contains"), edge("acct:1", 60, "contains"), edge("acct:1", 70, "contains"), edge("acct:2", 80, "contains"),
    edge(10, 20, "contains"), edge(10, 21, "contains"), edge(10, 40, "contains"), edge(20, 30, "contains"), edge(20, 31, "contains"), edge(21, 50, "contains"),
    edge(30, 40, "secured_by"), edge(50, 40, "secured_by"), edge(30, "grp:1:project:shop", "member_of"), edge(50, "grp:1:project:shop", "member_of"),
    edge(80, 70, "references", "llm"),
  ],
};
const g = indexGraph(payload);
const at = (ref: number) => g.byId.get(`res:${ref}`)!;
const refs = (ids: Iterable<number>) => [...ids].map((i) => g.nodes[i].ref).sort((a, b) => a - b);
const ask = (over: Partial<Ask> = {}): Ask => ({ ...NO_ASK, ...over });

describe("around — a resource and what is one link away", () => {
  it("takes every kind of link, in either direction", () => {
    expect(refs(around(g, at(30)))).toEqual([20, 30, 40]);
    expect(refs(around(g, at(40)))).toEqual([10, 30, 40, 50]);
    expect(refs(around(g, at(70)))).toEqual([70, 80]);                 // an inferred relation counts as a link
  });
});

describe("path — the shortest chain of links between two resources", () => {
  it("finds it, ends included", () => {
    expect(path(g, at(31), at(50))!.map((i) => g.nodes[i].ref)).toEqual([31, 20, 10, 21, 50]);
    expect(path(g, at(30), at(50))!.map((i) => g.nodes[i].ref)).toEqual([30, 40, 50]);      // through the shared security group
  });
  it("is nothing when there is none, when both ends are the same, or when it would be too long", () => {
    expect(path(g, at(30), at(80))).toBeNull();                        // another account, and no relation between them
    expect(path(g, at(30), at(30))).toBeNull();
    expect(path(g, at(31), at(50), 2)).toBeNull();
  });
});

describe("a path says which of its links a model only inferred", () => {
  // final review: «隔了 1 步：EC2-1 → RDS-4» was stated as fact over a link a model guessed, while the route over
  // rule relations had three links. 542 of the 1,526 links of the measured build are inferred.
  const guessed = indexGraph({ ...payload, edges: [...payload.edges, edge(31, 50, "references", "llm")] });
  const ix = (ref: number) => guessed.byId.get(`res:${ref}`)!;

  it("takes the route over relations the rules found when there is one, however short the guessed one is", () => {
    expect(path(guessed, ix(31), ix(50))!.map((i) => guessed.nodes[i].ref)).toEqual([31, 20, 10, 21, 50]);
    const sc = scene(guessed, ask({ a: ix(31), b: ix(50) }), null);
    expect(sc.pathHops!.map((h) => [h.r, h.llm])).toEqual([["contains", false], ["contains", false], ["contains", false], ["contains", false]]);
    expect(sc.pathInferred).toBe(0);
  });

  it("goes over an inferred link only when nothing else joins the two — and then says which link that is", () => {
    const sc = scene(g, ask({ a: at(80), b: at(70) }), null);                    // the only link between them is a model's guess
    expect(sc.path!.map((i) => g.nodes[i].ref)).toEqual([80, 70]);
    expect(sc.pathHops).toEqual([{ k: g.edges.findIndex((e) => e.llm), r: "references", llm: true, fwd: true }]);
    expect(sc.pathInferred).toBe(1);
  });

  it("says which way each link is written — a path may run against it", () => {
    // found in the browser on the real graph: «sg_web —contains→ project-vpc» read as the group holding the VPC,
    // while the build wrote «project-vpc contains sg_web». The arrow is the relation's, not the path's.
    const sc = scene(g, ask({ a: at(31), b: at(50) }), null);         // instance 31 ← subnet 20 ← VPC 10 → subnet 21 → database 50
    expect(sc.pathHops!.map((h) => [h.r, h.fwd])).toEqual([["contains", false], ["contains", false], ["contains", true], ["contains", true]]);
    expect(sc.pathHops!.map((h) => hopMarks(h).join("contains"))).toEqual(["←contains—", "←contains—", "—contains→", "—contains→"]);
  });

  it("has no hops when there is no path", () => {
    const sc = scene(g, ask({ a: at(30), b: at(80) }), null);
    expect([sc.path, sc.pathHops, sc.pathInferred]).toEqual([null, null, 0]);
  });
});

describe("search — by name, type, id, or the number of an item waiting on you", () => {
  const waiting = [{ id: "I12", ref: 50 }, { id: "C3", ref: null }];
  it("finds by a part of the name or of the type, case ignored", () => {
    expect(refs(search(g, "WEB", waiting))).toEqual([30, 31]);
    expect(refs(search(g, "subnet", waiting))).toEqual([20, 21]);
  });
  it("puts what has something open first, then names that start with the text", () => {
    expect(search(g, "web", waiting).map((i) => g.nodes[i].ref)).toEqual([30, 31]);         // web-1 is critical
    expect(search(g, "s", waiting).map((i) => g.nodes[i].ref).slice(0, 3)).toEqual([50, 70, 20]);   // warning, notice, then «subnet-20»
  });
  it("finds the resource an item sits on by the item's number", () => {
    expect(refs(search(g, "I#12", waiting))).toEqual([50]);
    expect(refs(search(g, "i12", waiting))).toEqual([50]);
    expect(search(g, "C3", waiting)).toEqual([]);                      // that change sits on no resource
  });
  it("finds a resource by its own id", () => {
    expect(refs(search(g, "res:40", waiting))).toEqual([40]);
  });
  it("lists at most eight, and nothing for an empty text", () => {
    expect(search(g, "", waiting)).toEqual([]);
    expect(search(g, "   ", waiting)).toEqual([]);
    expect(search(g, "-", waiting, 3)).toHaveLength(3);
  });
});

describe("scene — ONE result that both views draw and every number on the page is read from", () => {
  it("with nothing asked: everything is bright, what is gone is marked, what is not normal wears a ring", () => {
    const sc = scene(g, ask(), null);
    expect(sc.dim).toBeNull();
    expect(refs(sc.gone)).toEqual([60]);
    expect(sc.shown).toBe(9);                                           // 10 resources, one of them gone
    expect(sc.rings.map((r) => [g.nodes[r.i].ref, r.tone, r.dim])).toEqual([[30, "critical", false], [50, "warning", false], [70, "notice", false]]);
    expect(refs(sc.labels)).toEqual([30, 50, 70]);                      // few enough to name
    expect(refs(sc.abnormal)).toEqual([30, 50, 70]);
    expect(sc.ties).toBeNull();                                         // the queue is not known: nothing is said about it
  });

  it("a resource that is gone wears no ring, even with an issue still open on it — and that is counted", () => {
    const sc = scene(g, ask(), null);
    expect(sc.rings.some((r) => g.nodes[r.i].ref === 60)).toBe(false);
    expect(sc.goneOpen).toBe(1);
  });

  it("filters dim what does not match; rings outside the view stay, faintly", () => {
    const sc = scene(g, ask({ type: "EC2" }), null);
    expect(refs(g.nodes.map((n) => n.i).filter((i) => !sc.dim!.has(i)))).toEqual([30, 31]);
    expect(sc.shown).toBe(2);
    expect(sc.rings.map((r) => [g.nodes[r.i].ref, r.dim])).toEqual([[30, false], [50, true], [70, true]]);
    expect(refs(sc.abnormal)).toEqual([30]);                            // the panel lists what the filters leave
  });

  it("filters by account, by tag group and by «only what is not normal»", () => {
    expect(scene(g, ask({ account: 2 }), null).shown).toBe(1);
    expect(refs([...g.nodes.keys()].filter((i) => !scene(g, ask({ group: "grp:1:project:shop" }), null).dim!.has(i)))).toEqual([30, 50]);
    expect(scene(g, ask({ onlyAbnormal: true }), null).shown).toBe(3);
  });

  it("«only what is around it» beats the filters; a path beats both", () => {
    const focus = scene(g, ask({ sel: at(30), focus: true, type: "S3" }), null);
    expect(refs([...g.nodes.keys()].filter((i) => !focus.dim!.has(i)))).toEqual([20, 30, 40]);
    expect(refs(focus.abnormal)).toEqual([70]);                         // …but the panel still lists by the filters
    const way = scene(g, ask({ sel: at(30), focus: true, a: at(31), b: at(50) }), null);
    expect(way.path!.map((i) => g.nodes[i].ref)).toEqual([31, 20, 10, 21, 50]);
    expect(refs([...g.nodes.keys()].filter((i) => !way.dim!.has(i)))).toEqual([10, 20, 21, 31, 50]);
  });

  it("two ends with no path between them dim nothing, and say there is none", () => {
    const sc = scene(g, ask({ a: at(30), b: at(80) }), null);
    expect([sc.path, sc.dim]).toEqual([null, null]);
  });

  it("a search highlights and names; it never hides", () => {
    const sc = scene(g, ask({ q: "web" }), null);
    expect(sc.dim).toBeNull();
    expect(refs(sc.hits)).toEqual([30, 31]);
    expect(refs(sc.labels)).toEqual([30, 31, 50, 70]);
  });

  it("names what is being looked at last, so those names end up on top", () => {
    const sc = scene(g, ask({ sel: at(31), a: at(10), b: at(21) }), null);
    expect(sc.labels.slice(-3).map((i) => g.nodes[i].ref)).toEqual([21, 10, 31]);
    expect(new Set(sc.labels).size).toBe(sc.labels.length);
  });

  it("does not name every ring when there are many — only what was asked about", () => {
    const many: GalaxyGraph = { build_id: 1, nodes: Array.from({ length: 20 }, (_, k) => res(k + 1, "EC2", { health: "warning" })), edges: [] };
    const big = indexGraph(many);
    const sc = scene(big, ask({ sel: 3 }), null);
    expect(sc.rings).toHaveLength(20);
    expect(sc.labels).toEqual([3]);
  });

  it("ties the map to the queue: which waiting items wear a ring, which sit on a quiet resource, which are on no resource", () => {
    const sc = scene(g, ask(), [{ id: "I12", ref: 50 }, { id: "I13", ref: 31 }, { id: "I14", ref: 60 }, { id: "C3", ref: null }, { id: "I15", ref: 999 }]);
    expect(sc.ties).toEqual({ ringed: ["I12"], quiet: ["I13", "I14"], offMap: ["C3", "I15"] });
  });
});

describe("expected / reconcile — the picture against the data", () => {
  const sc = scene(g, ask({ type: "EC2" }), null);
  const want: Drawn = { nodes: 10, bright: 2, gone: 1, rings: 3, ringsBright: 1, links: 3, named: 1 };
  it("says what a view must have drawn for this result", () => {
    expect(expected(sc)).toEqual(want);                                 // links: 9 between resources, 6 of them containment
  });
  it("agrees when the view drew exactly that", () => {
    expect(reconcile(sc, { ...want })).toEqual([]);
  });
  it("names every number that differs", () => {
    expect(reconcile(sc, { ...want, rings: 2, links: 4 })).toEqual([{ what: "rings", want: 3, got: 2 }, { what: "links", want: 3, got: 4 }]);
  });
  it("counts what a view left out because it is off the screen with what it drew", () => {
    const none: Drawn = { nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0 };
    // drawn + off the screen = what the scene asks for
    expect(reconcile(sc, { ...want, nodes: 7, bright: 1, rings: 2, links: 2 }, "2d", { ...none, nodes: 3, bright: 1, rings: 1, links: 1 })).toEqual([]);
    // … and one that is in neither count is still missed
    expect(reconcile(sc, { ...want, nodes: 7 }, "2d", { ...none, nodes: 2 })).toEqual([{ what: "nodes", want: 10, got: 9 }]);
  });
});

describe("confirm — one check that disagrees is not yet a red card", () => {
  // final review: the card could be red for a second without cause — the 3D engine builds its objects over a few
  // frames, and a check can land in between
  const m = [{ what: "rings" as const, want: 3, got: 2 }];
  it("shows agreement at once", () => {
    expect(confirm([], 1)).toEqual({ show: [], strikes: 0 });
  });
  it("holds the first mismatch back: the card stays as it was", () => {
    expect(confirm(m, 0)).toEqual({ show: undefined, strikes: 1 });
  });
  it("shows the mismatch when the next check finds one too, and keeps showing it", () => {
    expect(confirm(m, 1)).toEqual({ show: m, strikes: 2 });
    expect(confirm(m, 2)).toEqual({ show: m, strikes: 3 });
  });
});

