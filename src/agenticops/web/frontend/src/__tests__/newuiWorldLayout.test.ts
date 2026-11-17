import { describe, expect, it } from "vitest";
import type { GalaxyGraph, GalaxyGraphEdge, GalaxyGraphNode } from "@/api/types";
import { indexGraph } from "@/newui/lib/world/graph";
import { layout, type Disc } from "@/newui/lib/world/layout";

const res = (ref: number, type: string, acct = 1): GalaxyGraphNode =>
  ({ id: `res:${ref}`, kind: "resource", name: `${type}-${ref}`, type, acct, health: "unknown", absent: false });
const holds = (s: string, t: string): GalaxyGraphEdge => ({ s, t, r: "contains", p: "rule" });

/** Two accounts. Account 1: two VPCs (one with two subnets holding instances, and security groups), 40 roles and 12
 *  buckets held by the account directly. Account 2: 5 roles. */
function sample(): GalaxyGraph {
  const nodes: GalaxyGraphNode[] = [{ id: "acct:1", kind: "account", name: "prod", type: "" }, { id: "acct:2", kind: "account", name: "dev", type: "" }];
  const edges: GalaxyGraphEdge[] = [];
  const add = (ref: number, type: string, parent: string, acct = 1) => { nodes.push(res(ref, type, acct)); edges.push(holds(parent, `res:${ref}`)); };
  add(10, "VPC", "acct:1"); add(11, "VPC", "acct:1");
  add(20, "Subnet", "res:10"); add(21, "Subnet", "res:10"); add(22, "Subnet", "res:11");
  for (let k = 0; k < 6; k++) add(30 + k, "EC2", k < 4 ? "res:20" : "res:21");
  for (let k = 0; k < 5; k++) add(40 + k, "SecurityGroup", "res:10");
  for (let k = 0; k < 40; k++) add(100 + k, "IAMRole", "acct:1");
  for (let k = 0; k < 12; k++) add(200 + k, "S3", "acct:1");
  for (let k = 0; k < 5; k++) add(300 + k, "IAMRole", "acct:2", 2);
  return { nodes, edges, build_id: 1 };
}

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

describe("layout — where each resource sits on the map", () => {
  const g = indexGraph(sample());
  const L = layout(g);
  const at = (ref: number) => g.nodes[g.byId.get(`res:${ref}`)!];
  const disc = (pred: (d: Disc) => boolean) => L.discs.find(pred)!;

  it("places every resource, at a finite spot inside the bounds", () => {
    for (const n of g.nodes) {
      expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true);
      expect(n.x >= L.bounds.x0 && n.x <= L.bounds.x1 && n.y >= L.bounds.y0 && n.y <= L.bounds.y1).toBe(true);
    }
  });

  it("puts no two resources on the same spot", () => {
    let closest = Infinity;
    for (let i = 0; i < g.nodes.length; i++) for (let j = i + 1; j < g.nodes.length; j++) closest = Math.min(closest, dist(g.nodes[i], g.nodes[j]));
    expect(closest).toBeGreaterThan(0.6);
  });

  it("is the same on every run, whatever order the build lists its nodes in", () => {
    const spots = g.nodes.map((n) => [n.ref, n.x, n.y]);
    const again = indexGraph(sample()); layout(again);
    expect(again.nodes.map((n) => [n.ref, n.x, n.y])).toEqual(spots);
    const shuffled = sample(); shuffled.nodes.reverse(); shuffled.edges.reverse();
    const other = indexGraph(shuffled); layout(other);
    expect(other.nodes.map((n) => [n.ref, n.x, n.y])).toEqual(spots);
  });

  it("draws one region per account, and they do not overlap", () => {
    const regions = L.discs.filter((d) => d.kind === "account");
    expect(regions.map((d) => [d.label, d.count])).toEqual([["prod", 68], ["dev", 5]]);
    expect(dist(regions[0], regions[1])).toBeGreaterThanOrEqual(regions[0].r + regions[1].r);
    for (const n of g.nodes) {
      const region = regions[n.acct === 1 ? 0 : 1];
      expect(dist(n, region)).toBeLessThanOrEqual(region.r);
    }
  });

  it("keeps what a resource holds inside its circle, with the resource at the centre", () => {
    const vpc = disc((d) => d.kind === "container" && d.node === at(10).i);
    expect([at(10).x, at(10).y]).toEqual([vpc.x, vpc.y]);
    for (const ref of [20, 21, 30, 31, 32, 33, 34, 35, 40, 41, 42, 43, 44]) expect(dist(at(ref), vpc)).toBeLessThanOrEqual(vpc.r);
    const subnet = disc((d) => d.kind === "container" && d.node === at(20).i);
    for (const ref of [30, 31, 32, 33]) expect(dist(at(ref), subnet)).toBeLessThanOrEqual(subnet.r);
    expect(dist(at(34), subnet)).toBeGreaterThan(subnet.r);            // an instance of the other subnet is not in this one
  });

  it("holds a part that is bigger than the holder's own surroundings — still inside, the holder still at the centre", () => {
    const nodes: GalaxyGraphNode[] = [{ id: "acct:1", kind: "account", name: "prod", type: "" }, res(1, "VPC"), res(2, "Subnet"), res(3, "SecurityGroup")];
    const edges = [holds("acct:1", "res:1"), holds("res:1", "res:2"), holds("res:1", "res:3")];
    for (let k = 0; k < 30; k++) { nodes.push(res(10 + k, "EC2")); edges.push(holds("res:2", `res:${10 + k}`)); }
    const big = indexGraph({ nodes, edges, build_id: 1 }); const BL = layout(big);
    const vpc = BL.discs.find((d) => d.kind === "container" && big.nodes[d.node].ref === 1)!;
    const holder = big.nodes[big.byId.get("res:1")!];
    expect([holder.x, holder.y]).toEqual([vpc.x, vpc.y]);
    for (const n of big.nodes) expect(dist(n, vpc)).toBeLessThanOrEqual(vpc.r);
    const subnet = BL.discs.find((d) => d.kind === "container" && big.nodes[d.node].ref === 2)!;
    expect(dist(subnet, vpc) + subnet.r).toBeLessThanOrEqual(vpc.r);
    expect(dist(holder, subnet)).toBeGreaterThan(subnet.r);              // the VPC's own dot is not inside its subnet's circle
  });

  it("keeps the circles of one level apart", () => {
    const a = disc((d) => d.node === at(10).i), b = disc((d) => d.node === at(11).i);
    expect(dist(a, b)).toBeGreaterThanOrEqual(a.r + b.r);
    const s20 = disc((d) => d.node === at(20).i), s21 = disc((d) => d.node === at(21).i);
    expect(dist(s20, s21)).toBeGreaterThanOrEqual(s20.r + s21.r);
  });

  it("gathers what the account holds directly into one cloud per type, named and counted", () => {
    const clouds = L.discs.filter((d) => d.kind === "cloud" && d.acct === 1).map((d) => [d.label, d.count]);
    expect(clouds).toEqual([["IAMRole", 40], ["S3", 12]]);
    const roles = disc((d) => d.kind === "cloud" && d.acct === 1 && d.label === "IAMRole");
    for (let k = 0; k < 40; k++) expect(dist(at(100 + k), roles)).toBeLessThanOrEqual(roles.r);
    for (let k = 0; k < 12; k++) expect(dist(at(200 + k), roles)).toBeGreaterThan(roles.r);
  });

  it("gives a resource with no account a region of its own, and says so", () => {
    const p = sample(); p.nodes.push({ id: "res:900", kind: "resource", name: "stray", type: "EBS", acct: null, health: "unknown", absent: false });
    const lost = indexGraph(p); const LL = layout(lost);
    expect(LL.discs.filter((d) => d.kind === "account").map((d) => d.label)).toEqual(["prod", "dev", ""]);
    expect(LL.discs.filter((d) => d.kind === "account")[2].acct).toBeNull();
  });

  it("an empty build has nothing to place", () => {
    const none = indexGraph({ nodes: [], edges: [], build_id: null });
    expect(layout(none)).toEqual({ discs: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } });
  });
});
