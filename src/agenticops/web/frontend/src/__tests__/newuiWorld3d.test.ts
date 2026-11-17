import { describe, expect, it } from "vitest";
import type { GalaxyGraph, GalaxyGraphEdge, GalaxyGraphNode } from "@/api/types";
import { depths, marks, nodeAlpha, ALPHA, readAlpha } from "@/newui/lib/world/depth";
import { indexGraph } from "@/newui/lib/world/graph";
import { layout } from "@/newui/lib/world/layout";
import { NO_ASK, expected, scene } from "@/newui/lib/world/scene";

const res = (ref: number, type: string, over: Partial<GalaxyGraphNode> = {}): GalaxyGraphNode =>
  ({ id: `res:${ref}`, kind: "resource", name: `${type}-${ref}`, type, acct: 1, health: "unknown", absent: false, ...over });
const edge = (s: number | string, t: number | string, r: string, p: "rule" | "llm" = "rule"): GalaxyGraphEdge =>
  ({ s: typeof s === "number" ? `res:${s}` : s, t: typeof t === "number" ? `res:${t}` : t, r, p });

const payload: GalaxyGraph = {
  build_id: 3,
  nodes: [
    { id: "acct:1", kind: "account", name: "prod", type: "" },
    res(10, "VPC"), res(20, "Subnet"), res(21, "Subnet"), res(30, "EC2", { health: "critical" }), res(31, "EC2"), res(40, "SecurityGroup"),
    res(50, "RDS", { health: "warning" }), res(60, "IAMRole", { absent: true, health: "notice" }), res(70, "S3", { health: "notice" }), res(80, "Lambda"),
    ...Array.from({ length: 30 }, (_, k) => res(100 + k, "IAMRole")),
  ],
  edges: [
    edge("acct:1", 10, "contains"), edge("acct:1", 60, "contains"), edge("acct:1", 70, "contains"), edge("acct:1", 80, "contains"),
    edge(10, 20, "contains"), edge(10, 21, "contains"), edge(10, 40, "contains"), edge(20, 30, "contains"), edge(20, 31, "contains"), edge(21, 50, "contains"),
    edge(30, 40, "secured_by"), edge(50, 40, "secured_by"), edge(80, 60, "uses"), edge(80, 70, "references", "llm"),
    ...Array.from({ length: 30 }, (_, k) => edge("acct:1", 100 + k, "contains")),
  ],
};

describe("depths — the third coordinate of the 3D view", () => {
  const g = indexGraph(payload), L = layout(g), z = depths(g, L);
  const at = (ref: number) => g.byId.get(`res:${ref}`)!;

  it("gives every resource a finite depth", () => {
    expect(z).toHaveLength(g.nodes.length);
    expect([...z].every(Number.isFinite)).toBe(true);
  });

  it("is the same on every run and for every order the build lists its nodes in", () => {
    const again = indexGraph(payload); const z2 = depths(again, layout(again));
    expect([...z2]).toEqual([...z]);
    const shuffled = { ...payload, nodes: [...payload.nodes].reverse(), edges: [...payload.edges].reverse() };
    const other = indexGraph(shuffled); const z3 = depths(other, layout(other));
    expect(other.nodes.map((n, i) => [n.ref, z3[i]])).toEqual(g.nodes.map((n, i) => [n.ref, z[i]]));
  });

  it("keeps what a resource holds near it in depth — inside the sphere of its circle", () => {
    const disc = (ref: number) => L.discs.find((d) => d.kind === "container" && d.node === at(ref))!;
    for (const [child, holder] of [[30, 20], [31, 20], [50, 21], [20, 10], [21, 10], [40, 10]]) {
      expect(Math.abs(z[at(child)] - z[at(holder)])).toBeLessThanOrEqual(disc(holder).r);
    }
  });

  it("spreads a cloud of one type in depth instead of leaving it a flat disc", () => {
    const roles = Array.from({ length: 30 }, (_, k) => z[at(100 + k)]);
    expect(Math.max(...roles) - Math.min(...roles)).toBeGreaterThan(1);
    const cloud = L.discs.find((d) => d.kind === "cloud" && d.label === "IAMRole")!;
    expect(Math.max(...roles.map(Math.abs))).toBeLessThanOrEqual(cloud.r);
  });
});

describe("nodeAlpha — how strongly a resource is drawn in 3D; the check reads these back from the engine", () => {
  const g = indexGraph(payload);
  const at = (ref: number) => g.byId.get(`res:${ref}`)!;
  it("draws a ringed resource at full strength, a plain one softer, one outside the view faint", () => {
    const sc = scene(g, { ...NO_ASK, type: "EC2" }, null);
    expect(nodeAlpha(sc, at(30))).toBe(ALPHA.ring);      // critical, in view
    expect(nodeAlpha(sc, at(31))).toBe(ALPHA.plain);
    expect(nodeAlpha(sc, at(50))).toBe(ALPHA.dim);       // ringed, but outside the view
    expect(nodeAlpha(sc, at(10))).toBe(ALPHA.dim);
  });
  it("draws a gone resource as gone — fainter still outside the view, never as a plain one", () => {
    expect(nodeAlpha(scene(g, { ...NO_ASK }, null), at(60))).toBe(ALPHA.gone);
    expect(nodeAlpha(scene(g, { ...NO_ASK, type: "EC2" }, null), at(60))).toBe(ALPHA.goneDim);
  });
  it("reads a drawn strength back as bright, gone or neither — the three do not overlap", () => {
    expect([ALPHA.ring, ALPHA.plain].map(readAlpha)).toEqual(["bright", "bright"]);
    expect([ALPHA.gone, ALPHA.goneDim].map(readAlpha)).toEqual(["gone", "gone"]);
    expect(readAlpha(ALPHA.dim)).toBe("dim");
  });
});

describe("marks — the rings and names laid over the 3D canvas", () => {
  const g = indexGraph(payload);
  const at = (ref: number) => g.byId.get(`res:${ref}`)!;
  it("is one mark per ring, plus the named resources that have none; what is being looked at comes last", () => {
    const sc = scene(g, { ...NO_ASK, sel: at(31) }, null);
    const m = marks(sc, at(31));
    expect(m.map((x) => [g.nodes[x.i].ref, x.ring, x.off, x.named, x.sel])).toEqual([
      [30, "critical", false, true, false], [50, "warning", false, true, false], [70, "notice", false, true, false],
      [31, null, false, true, true],
    ]);
  });
  it("keeps a ring outside the view, faintly and without its name", () => {
    const m = marks(scene(g, { ...NO_ASK, type: "EC2" }, null), null);
    expect(m.map((x) => [g.nodes[x.i].ref, x.off, x.named])).toEqual([[50, true, false], [70, true, false], [30, false, true]]);
  });
  it("marks a named resource that is gone", () => {
    const m = marks(scene(g, { ...NO_ASK, sel: at(60) }, null), at(60));
    expect(m.find((x) => g.nodes[x.i].ref === 60)).toMatchObject({ gone: true, ring: null, sel: true });
  });
});

describe("expected — what each view must have on its canvas", () => {
  const g = indexGraph(payload), sc = scene(g, { ...NO_ASK }, null);
  it("the flat map draws every link but containment; the 3D view draws every link", () => {
    expect(expected(sc).links).toBe(4);
    expect(expected(sc, "2d").links).toBe(4);
    expect(expected(sc, "3d").links).toBe(10);
    expect({ ...expected(sc, "3d"), links: 0 }).toEqual({ ...expected(sc, "2d"), links: 0 });      // everything else is the same result
  });
});
