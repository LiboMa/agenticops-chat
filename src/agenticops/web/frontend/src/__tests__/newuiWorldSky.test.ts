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

class Path { moveTo() {} lineTo() {} arc() {} }
const noop = () => {};
function fakeCanvas() {
  const ctx = new Proxy({ measureText: () => ({ width: 40 }) } as Record<string, unknown>, {
    get: (o, k: string) => (k in o ? o[k] : noop), set: () => true,
  });
  return { clientWidth: 1200, clientHeight: 800, width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
}

let frame: ((ts: number) => void) | null = null;
beforeEach(() => {
  frame = null;
  vi.stubGlobal("window", { devicePixelRatio: 1, addEventListener: noop, removeEventListener: noop });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "#fff" }));
  vi.stubGlobal("Path2D", Path);
  vi.stubGlobal("requestAnimationFrame", (f: (ts: number) => void) => { frame = f; return 1; });
  vi.stubGlobal("cancelAnimationFrame", noop);
  vi.stubGlobal("performance", { now: () => 0 });
});
afterEach(() => vi.unstubAllGlobals());

function drawOnce(ask: Partial<Ask>, world = true) {
  const g = indexGraph(payload), L = layout(g);
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
