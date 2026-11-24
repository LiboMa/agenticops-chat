import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GalaxyGraph, GalaxyGraphEdge, GalaxyGraphNode } from "@/api/types";
import { indexGraph } from "@/newui/lib/world/graph";
import { layout } from "@/newui/lib/world/layout";
import { NO_ASK, expected, reconcile, scene, type Ask } from "@/newui/lib/world/scene";
import { Sky } from "@/newui/world/Sky";

/** The renderer on a canvas that only counts: it runs the real draw code, so what it reports having drawn is what
 *  the real canvas would get. The check card compares that report with the scene — these tests prove the report is
 *  right when the renderer is right, and that a renderer which draws less is caught. */

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
  ],
  edges: [
    edge("acct:1", 10, "contains"), edge("acct:1", 60, "contains"), edge("acct:1", 70, "contains"), edge("acct:1", 80, "contains"),
    edge(10, 20, "contains"), edge(10, 21, "contains"), edge(10, 40, "contains"), edge(20, 30, "contains"), edge(20, 31, "contains"), edge(21, 50, "contains"),
    edge(30, 40, "secured_by"), edge(50, 40, "secured_by"), edge(80, 60, "uses"), edge(80, 70, "references", "llm"),
  ],
};

/** A canvas that records what is put on it: every arc with its radius and the colour set at that moment, every
 *  stroke and fill with its style, dash and line width, every text. The real draw code runs on it — so a ring that is
 *  not drawn, drawn in another tone, or a guessed link drawn as a fact shows here, not only in a count. */
class Path { arcs: number[] = []; lines = 0; moveTo() {} lineTo() { this.lines++; } arc(_x: number, _y: number, r: number) { this.arcs.push(r); } }
interface Call { op: "arc" | "stroke" | "fill" | "text" | "line"; x?: number; y?: number; r?: number; stroke?: string; fill?: string; dash?: number[]; width?: number; path?: Path; text?: string }
const noop = () => {};
let calls: Call[] = [];
function fakeCanvas() {
  const st = { strokeStyle: "", fillStyle: "", lineWidth: 1, dash: [] as number[] };
  const ctx: Record<string, unknown> = {
    measureText: () => ({ width: 40 }),
    arc: (x: number, y: number, r: number) => { calls.push({ op: "arc", x, y, r, stroke: st.strokeStyle, fill: st.fillStyle }); },
    lineTo: () => { calls.push({ op: "line", stroke: st.strokeStyle, dash: [...st.dash], width: st.lineWidth }); },
    stroke: (p?: Path) => { calls.push({ op: "stroke", stroke: st.strokeStyle, dash: [...st.dash], width: st.lineWidth, path: p }); },
    fill: (p?: Path) => { calls.push({ op: "fill", fill: st.fillStyle, path: p }); },
    fillText: (text: string) => { calls.push({ op: "text", text }); },
    setLineDash: (d: number[]) => { st.dash = d; },
  };
  for (const k of ["strokeStyle", "fillStyle", "lineWidth"] as const) {
    Object.defineProperty(ctx, k, { get: () => st[k], set: (v: never) => { st[k] = v; } });
  }
  const proxy = new Proxy(ctx, { get: (o, k: string) => (k in o ? o[k] : noop), set: (o, k: string, v) => { if (k in st) (o as Record<string, unknown>)[k] = v; return true; } });
  return { clientWidth: 1200, clientHeight: 800, width: 0, height: 0, getContext: () => proxy } as unknown as HTMLCanvasElement;
}
/** arcs and line segments on the batched paths that were really stroked or filled */
const batched = () => {
  const paths = [...new Set(calls.filter((c) => (c.op === "stroke" || c.op === "fill") && c.path).map((c) => c.path!))];
  return { arcs: paths.flatMap((p) => p.arcs), lines: paths.reduce((n, p) => n + p.lines, 0) };
};

let frame: ((ts: number) => void) | null = null;
let still = false;
beforeEach(() => {
  frame = null;
  calls = [];
  still = false;
  vi.stubGlobal("window", { devicePixelRatio: 1, addEventListener: noop, removeEventListener: noop });
  vi.stubGlobal("matchMedia", () => ({ matches: still }));
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: (name: string) => name }));       // a colour is its variable's name: «--red»
  vi.stubGlobal("Path2D", Path);
  vi.stubGlobal("requestAnimationFrame", (f: (ts: number) => void) => { frame = f; return 1; });
  vi.stubGlobal("cancelAnimationFrame", noop);
  vi.stubGlobal("performance", { now: () => 0 });
});
afterEach(() => vi.unstubAllGlobals());

function drawOnce(ask: Partial<Ask>, world = true, source: GalaxyGraph = payload) {
  const g = indexGraph(source), L = layout(g);
  const full: Ask = { ...NO_ASK, ...ask };
  const sc = scene(g, full, null);
  const sky = new Sky(fakeCanvas(), {} as HTMLElement);
  sky.setGraph(g, L);
  sky.setMode({ world, inset: { left: 0, right: 0, top: 0, bottom: 0 } });
  sky.apply(sc, full.sel, g);
  sky.start();
  frame!(16);
  return { g, sc, sky };
}

describe("Sky — what the canvas reports having drawn", () => {
  it("is exactly what the scene asks for, with nothing asked", () => {
    const { sc, sky } = drawOnce({});
    expect(sky.stats()).toEqual(expected(sc));
    expect(sky.stats()).toEqual({ nodes: 10, bright: 9, gone: 1, rings: 3, ringsBright: 3, links: 4, named: 3 });
    expect(reconcile(sc, sky.stats())).toEqual([]);
  });

  it("is exactly what the scene asks for under a filter, a focus, a path and a search", () => {
    const at = (g: ReturnType<typeof indexGraph>, ref: number) => g.byId.get(`res:${ref}`)!;
    const g0 = indexGraph(payload);
    for (const ask of [
      { type: "EC2" }, { onlyAbnormal: true }, { sel: at(g0, 30), focus: true }, { a: at(g0, 31), b: at(g0, 50) }, { q: "ec2" },
      { sel: at(g0, 60) }, { account: 2 },
    ] as Partial<Ask>[]) {
      const { sc, sky } = drawOnce(ask);
      expect(reconcile(sc, sky.stats()), JSON.stringify(ask)).toEqual([]);
    }
  });

  it("names nothing while it is only a backdrop — and says so in what it reports", () => {
    const { sc, sky } = drawOnce({}, false);
    expect(sky.stats().named).toBe(0);
    expect(reconcile(sc, sky.stats())).toEqual([{ what: "named", want: 3, got: 0 }]);     // a backdrop is not checked; a world view that named nothing would be
  });

  it("a canvas that drew one ring less is caught", () => {
    const { sc, sky } = drawOnce({});
    const short = { ...sky.stats(), rings: sky.stats().rings - 1, ringsBright: sky.stats().ringsBright - 1 };
    expect(reconcile(sc, short)).toEqual([{ what: "rings", want: 3, got: 2 }, { what: "ringsBright", want: 3, got: 2 }]);
  });

  it("draws a result that was handed over BEFORE its graph — the lens's effect runs before the data layer's", () => {
    // found by the check card on a real page: the canvas drew every resource bright, no ring, nothing gone
    const g = indexGraph(payload), L = layout(g), sc = scene(g, { ...NO_ASK }, null);
    const sky = new Sky(fakeCanvas(), {} as HTMLElement);
    sky.setMode({ world: true, inset: { left: 0, right: 0, top: 0, bottom: 0 } });
    sky.apply(sc, null, g);            // the lens first …
    sky.setGraph(g, L);                // … then the data layer
    sky.start();
    frame!(16);
    expect(reconcile(sc, sky.stats())).toEqual([]);
  });

  it("never draws one build's result on another build's graph", () => {
    const g1 = indexGraph(payload), sc1 = scene(g1, { ...NO_ASK }, null);
    const g2 = indexGraph({ ...payload, nodes: payload.nodes.slice(0, 5), edges: [] });
    const sky = new Sky(fakeCanvas(), {} as HTMLElement);
    sky.setMode({ world: true, inset: { left: 0, right: 0, top: 0, bottom: 0 } });
    sky.setGraph(g2, layout(g2));
    sky.apply(sc1, null, g1);          // a stale result: its indexes mean other resources on g2
    sky.start();
    frame!(16);
    expect(sky.stats()).toMatchObject({ nodes: 4, rings: 0, gone: 0, named: 0 });
  });

  it("draws nothing, and reports nothing, without a graph", () => {
    const sky = new Sky(fakeCanvas(), {} as HTMLElement);
    sky.start();
    frame!(16);
    expect(sky.stats()).toEqual({ nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0 });
  });

  it("picks the resource under the pointer, a ringed one before a plain neighbour", () => {
    const { g, sky } = drawOnce({});
    const spot = (ref: number) => { const n = g.nodes[g.byId.get(`res:${ref}`)!]; return n; };
    // after one frame the camera is still easing; ask where the node landed by picking at every node's own spot
    const s = sky as unknown as { sx: Float32Array; sy: Float32Array };
    const i = spot(30).i;
    expect(sky.pick(s.sx[i], s.sy[i])).toBe(i);
    expect(sky.pick(-500, -500)).toBeNull();
  });
});

describe("Sky — what is really put on the canvas", () => {
  // final review: the counts were tallied before the off-screen test and before any canvas call, on a canvas that
  // recorded nothing — deleting a ring's arc and stroke passed every test and left the card green
  it("puts every resource and every line on a path that is then drawn", () => {
    still = true;                                         // reduced motion: no pulse, so a ring's radius is exactly 7
    const { sc, sky } = drawOnce({});
    const b = batched();
    expect(b.arcs.length).toBe(sc.totals.nodes);                                    // ten stars, the gone one among them
    expect(b.arcs.filter((r) => r === 3.2).length).toBe(sc.gone.size);              // … as a hollow glyph of its own
    expect(b.lines).toBe(sc.totals.lines);
    expect(sky.culled()).toEqual({ nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0 });   // all of it is on the screen here
  });

  it("counts what is off the screen apart from what it drew — the two together are what the scene asks for", () => {
    still = true;
    const { g, sc, sky } = drawOnce({});
    sky.flyTo(g.byId.get("res:30")!);                     // close in on one resource: most of the map leaves the screen
    for (let k = 2; k < 80; k++) frame!(16 * k);          // let the camera arrive
    calls = [];
    frame!(16 * 80);
    const drawn = sky.stats(), off = sky.culled();
    expect(off.nodes).toBeGreaterThan(0);
    expect(off.rings).toBeGreaterThan(0);
    const b = batched();
    expect(b.arcs.length).toBe(drawn.nodes);                                        // only what is on the screen went onto a path
    expect(b.lines).toBe(drawn.links);
    expect(calls.filter((c) => c.op === "arc" && c.r === 7).length).toBe(drawn.rings);
    expect(drawn.nodes + off.nodes).toBe(sc.totals.nodes);
    expect(drawn.rings + off.rings).toBe(sc.rings.length);
    expect(drawn.links + off.links).toBe(sc.totals.lines);
    expect(reconcile(sc, drawn)).not.toEqual([]);                                   // what was drawn alone is short …
    expect(reconcile(sc, drawn, "2d", off)).toEqual([]);                            // … with what is off the screen it is all there
  });

  it("draws one ring per resource with something open, each in its own tone", () => {
    still = true;
    const { sc } = drawOnce({});
    const rings = calls.filter((c) => c.op === "arc" && c.r === 7);
    expect(rings.map((c) => c.stroke).sort()).toEqual(["--amber", "--mint", "--red"]);   // warning, notice, critical
    expect(rings.length).toBe(sc.rings.length);
  });

  it("writes the names the scene asks for", () => {
    still = true;
    const { g, sc } = drawOnce({});
    const texts = calls.filter((c) => c.op === "text").map((c) => c.text);
    for (const i of sc.labels) expect(texts).toContain(g.nodes[i].name);
  });

  it("draws a guessed link of a path dashed, and a path over rule relations solid", () => {
    still = true;
    const at = (g: ReturnType<typeof indexGraph>, ref: number) => g.byId.get(`res:${ref}`)!;
    const g0 = indexGraph(payload);
    const pathLines = () => calls.filter((c) => c.op === "line" && c.stroke === "--mint" && c.width === 2.2);
    drawOnce({ a: at(g0, 31), b: at(g0, 50) });                                     // subnet, VPC, subnet: four rule links
    expect(pathLines().map((c) => c.dash!.length > 0)).toEqual([false, false, false, false]);
    calls = [];
    const lone = { ...payload, edges: payload.edges.filter((e) => !(e.s === "res:80" && e.r === "uses")) };
    const g1 = indexGraph(lone);
    drawOnce({ a: at(g1, 80), b: at(g1, 70) }, true, lone);                         // only a model's guess joins these two
    expect(pathLines().map((c) => c.dash!.length > 0)).toEqual([true]);
  });

  it("runs a dot on each link of the open resource that has a direction — none on a guessed one, two on a two-way one", () => {
    const at = (g: ReturnType<typeof indexGraph>, ref: number) => g.byId.get(`res:${ref}`)!;
    const g0 = indexGraph(payload);
    const dots = () => calls.filter((c) => c.op === "arc" && c.r === 2.2 && c.fill === "--mint").length;
    drawOnce({ sel: at(g0, 30) });            // held by its subnet (contains) and secured by a group: one dot each
    expect(dots()).toBe(2);
    calls = [];
    drawOnce({ sel: at(g0, 80) });            // uses a role: one dot; a model thinks it refers to a bucket: none
    expect(dots()).toBe(1);
    calls = [];
    const both = { ...payload, edges: [...payload.edges, edge(31, 50, "same_as")] };
    drawOnce({ sel: indexGraph(both).byId.get("res:31")! }, true, both);            // held by its subnet: one; same_as: one each way
    expect(dots()).toBe(3);
  });

  it("starts each dot at the end a fault would come from", () => {
    // final review: flipping the direction in the renderer passed every test. The first frame puts a dot less than
    // half way along its link (the first two links of a resource), so the end it is nearer to is the end it left.
    const { g, sky } = drawOnce({ sel: indexGraph(payload).byId.get("res:21")! });  // Subnet-21: held by VPC-10, holds RDS-50
    const s = sky as unknown as { sx: Float32Array; sy: Float32Array };
    const at = (ref: number) => { const i = g.byId.get(`res:${ref}`)!; return { x: s.sx[i], y: s.sy[i] }; };
    const far = (p: { x: number; y: number }, q: { x: number; y: number }) => Math.hypot(p.x - q.x, p.y - q.y);
    const on = (d: { x: number; y: number }, p: { x: number; y: number }, q: { x: number; y: number }) => Math.abs(far(d, p) + far(d, q) - far(p, q)) < 0.01;
    const dots = calls.filter((c) => c.op === "arc" && c.r === 2.2 && c.fill === "--mint").map((c) => ({ x: c.x!, y: c.y! }));
    expect(dots.length).toBe(2);
    const vpc = at(10), subnet = at(21), rds = at(50);
    const down = dots.find((d) => on(d, subnet, rds))!, up = dots.find((d) => on(d, vpc, subnet))!;
    expect(far(down, subnet)).toBeLessThan(far(down, rds));        // a fault in the subnet reaches what it holds: the dot leaves the subnet
    expect(far(up, vpc)).toBeLessThan(far(up, subnet));            // a fault in the VPC reaches the subnet: the dot leaves the VPC
  });
});

