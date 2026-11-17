import ForceGraph3D, { type ForceGraph3DInstance } from "3d-force-graph";
import { ALPHA, depths, marks, nodeAlpha, readAlpha, type Mark } from "../lib/world/depth";
import type { WorldGraph } from "../lib/world/graph";
import type { Disc, Layout } from "../lib/world/layout";
import { flow } from "../lib/world/relations";
import type { Drawn, RingTone, Scene } from "../lib/world/scene";

/** The 3D view of «全景». Like the flat map it decides nothing: it draws the result lib/world/scene hands it, and
 *  reports what is on its canvas — read back from the ENGINE'S OWN objects (how many spheres, how many of them at
 *  full strength, how many drawn as gone, how many lines) and from the page elements laid over it (rings, names) —
 *  so the lens can check it against the data.
 *
 *  The engine (3d-force-graph on three.js) is in this module only, and this module is imported the first time
 *  someone switches to 3D: nobody who stays on the flat map downloads it. Its version is pinned exactly
 *  (package.json): `stats` reads the engine's internal `__threeObj` / `__lineObj`. */

const SCALE = 5;                                    // map units → engine units
const TONE_VAR: Record<RingTone, "red" | "amber" | "mint"> = { critical: "red", warning: "amber", notice: "mint" };

interface N3 { id: number; x: number; y: number; z: number; fx: number; fy: number; fz: number; __threeObj?: { material?: { opacity: number } } }
interface L3 { source: number | N3; target: number | N3; a: number; b: number; k: number; __lineObj?: unknown }
interface Vec { x: number; y: number; z: number; project: (camera: unknown) => Vec }
type Colors = Record<"star" | "amber" | "mint" | "red" | "chalk", string>;

export interface Sky3Handlers { pick: (i: number | null) => void; hover: (i: number | null, x: number, y: number) => void }

export class Sky3 {
  fps = 0;
  turning = false;
  private G: ForceGraph3DInstance<N3, L3>;
  private V3: new (x: number, y: number, z: number) => Vec;
  private g: WorldGraph | null = null;
  private discs: Disc[] = [];
  private nodes: N3[] = [];
  private holders = new Set<number>();
  private sc: Scene | null = null;
  private scOf: WorldGraph | null = null;
  private sel: number | null = null;
  private list: Mark[] = [];
  private colors: Colors = { star: "255,255,255", amber: "#fb2", mint: "#5ec", red: "#f77", chalk: "#eee" };
  private raf = 0;
  private frames = 0;
  private fpsAt = 0;
  private pointer = { x: 0, y: 0 };
  private span = 1000;
  private inset = { left: 0, right: 0 };
  private readonly still: boolean;
  private readonly onResize = () => { this.G.width(window.innerWidth).height(window.innerHeight); this.offset(); };
  private readonly onMove = (e: PointerEvent) => { this.pointer = { x: e.clientX, y: e.clientY }; };
  private readonly onDown = () => { if (this.turning) this.turn(false); };       // taking the map in hand stops the turning

  constructor(private host: HTMLElement, private labels: HTMLElement, private clabels: HTMLElement, private root: HTMLElement, private on: Sky3Handlers) {
    this.still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    // the package's default export is typed for its own node / link shapes; ours are narrower versions of them
    const Engine = ForceGraph3D as unknown as new (el: HTMLElement, options?: { controlType?: "orbit" }) => ForceGraph3DInstance<N3, L3>;
    this.G = new Engine(host, { controlType: "orbit" });
    this.G.backgroundColor("rgba(0,0,0,0)").showNavInfo(false).enableNodeDrag(false).nodeRelSize(2.1).nodeResolution(6).nodeOpacity(1).nodeLabel(() => "")
      .linkOpacity(1).linkDirectionalParticleSpeed(0.006).linkDirectionalParticleWidth(2.4).linkDirectionalParticleColor(() => this.colors.mint)
      .cooldownTicks(0).warmupTicks(0)
      .onNodeClick((d) => this.on.pick(d.id))
      .onBackgroundClick(() => this.on.pick(null))
      .onNodeHover((d) => { host.style.cursor = d ? "pointer" : "grab"; this.on.hover(d ? d.id : null, this.pointer.x, this.pointer.y); });
    this.V3 = (this.G.camera() as unknown as { position: { constructor: new (x: number, y: number, z: number) => Vec } }).position.constructor;
    host.addEventListener("pointermove", this.onMove);
    host.addEventListener("pointerdown", this.onDown);
    window.addEventListener("resize", this.onResize);
    this.recolor();
  }

  dispose(): void {
    cancelAnimationFrame(this.raf);
    this.host.removeEventListener("pointermove", this.onMove);
    this.host.removeEventListener("pointerdown", this.onDown);
    window.removeEventListener("resize", this.onResize);
    this.G._destructor();
  }

  recolor(): void {
    const cs = getComputedStyle(this.root), v = (n: string) => cs.getPropertyValue(n).trim();
    this.colors = { star: v("--star"), amber: v("--amber"), mint: v("--mint"), red: v("--red"), chalk: v("--chalk") };
    this.style();
  }

  setGraph(g: WorldGraph | null, layout: Layout | null): void {
    if (g === this.g) return;
    this.g = g;
    this.discs = (layout?.discs ?? []).filter((d) => d.kind === "account");
    const z = g && layout ? depths(g, layout) : new Float32Array(0);
    const b = layout?.bounds ?? { x0: -1, y0: -1, x1: 1, y1: 1 }, cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
    this.span = Math.max(b.x1 - b.x0, b.y1 - b.y0) * SCALE;
    this.holders = new Set(g?.nodes.filter((n) => n.parent >= 0).map((n) => n.parent));
    this.nodes = (g?.nodes ?? []).map((n) => {
      const x = (n.x - cx) * SCALE, y = -(n.y - cy) * SCALE, d = z[n.i] * SCALE;
      return { id: n.i, x, y, z: d, fx: x, fy: y, fz: d };
    });
    // a dot runs from a link's source to its target: for a relation whose fault travels the other way round, the
    // link is handed to the engine reversed (a / b stay as the build wrote them)
    const links: L3[] = (g?.edges ?? []).map((e, k) => {
      const back = flow({ r: e.r, p: e.llm ? "llm" : "rule" }) === "reverse";
      return { source: back ? e.b : e.a, target: back ? e.a : e.b, a: e.a, b: e.b, k };
    });
    this.G.graphData({ nodes: this.nodes, links });
    this.discs = this.discs.map((d) => ({ ...d, x: (d.x - cx) * SCALE, y: -(d.y - cy) * SCALE, r: d.r * SCALE }));
    this.home(0);
    this.style();
  }

  /** Hand over what to show, which resource is open, and the graph both were worked out on (see Sky.apply). */
  apply(sc: Scene | null, sel: number | null, of: WorldGraph | null): void { this.sc = sc; this.sel = sel; this.scOf = of; this.style(); }

  private style(): void {
    const g = this.g, sc = this.scOf === g ? this.sc : null, sel = sc ? this.sel : null, C = this.colors;
    if (!g) return;
    const ring = new Map(sc?.rings.map((r) => [r.i, r] as const));
    const dim = (i: number) => !!sc?.dim && sc.dim.has(i);
    const onPath = (l: L3) => !!sc?.path && sc.path.some((i, k) => k > 0 && ((sc.path![k - 1] === l.a && i === l.b) || (sc.path![k - 1] === l.b && i === l.a)));
    const ofSel = (l: L3) => sel !== null && !sc?.path && (l.a === sel || l.b === sel);
    this.G
      .nodeColor((d) => { const r = ring.get(d.id); return r && !r.dim ? C[TONE_VAR[r.tone]] : `rgba(${C.star},${sc ? nodeAlpha(sc, d.id) : ALPHA.plain})`; })
      .nodeVal((d) => (ring.has(d.id) ? 14 : this.holders.has(d.id) ? 6 : 1.4))
      .linkColor((l) => onPath(l) ? C.mint : ofSel(l) ? C.chalk : dim(l.a) || dim(l.b) ? `rgba(${C.star},.03)`
        : `rgba(${C.star},${g.edges[l.k].contain ? 0.1 : g.edges[l.k].llm ? 0.5 : 0.28})`)
      .linkWidth((l) => (onPath(l) ? 2.2 : ofSel(l) ? 1 : 0))
      .linkCurvature((l) => (g.edges[l.k].llm ? 0.32 : 0))                // a relation a model inferred is a curve (the flat map dashes it)
      // a dot only where the direction is known and one-way: a two-way relation gets none rather than one that picks a side
      .linkDirectionalParticles((l) => {
        const way = flow({ r: g.edges[l.k].r, p: g.edges[l.k].llm ? "llm" : "rule" });
        return ofSel(l) && !this.still && (way === "forward" || way === "reverse") ? 2 : 0;
      });
    this.list = sc ? marks(sc, sel) : [];
  }

  show(on: boolean): void {
    for (const el of [this.host, this.labels, this.clabels]) el.hidden = !on;
    cancelAnimationFrame(this.raf);
    if (on) { this.onResize(); this.G.resumeAnimation(); this.raf = requestAnimationFrame(this.frame); }
    else this.G.pauseAnimation();
  }

  /** How much of the screen the panels cover on the left and the right: the picture is centred in what is left. */
  setInset(left: number, right: number): void {
    if (left === this.inset.left && right === this.inset.right) return;
    this.inset = { left, right };
    this.offset();
  }

  private offset(): void {
    const cam = this.G.camera() as unknown as { setViewOffset?: (fw: number, fh: number, x: number, y: number, w: number, h: number) => void; clearViewOffset?: () => void };
    const W = window.innerWidth, H = window.innerHeight, shift = (this.inset.left - this.inset.right) / 2;
    if (shift) cam.setViewOffset?.(W, H, -shift, 0, W, H); else cam.clearViewOffset?.();
  }

  /** The whole map, from far enough for it to fit into what the panels leave free. */
  home(ms = 900): void {
    const W = window.innerWidth, free = Math.max(240, W - this.inset.left - this.inset.right);
    const far = this.span * (W < 760 ? 1.5 : 0.95) * Math.min(2.2, W / free);
    this.G.cameraPosition({ x: 0, y: -far * 0.12, z: far }, { x: 0, y: 0, z: 0 }, ms);
  }

  flyTo(i: number, ms = 1000): void {
    const p = this.nodes[i];
    if (!p) return;
    const far = this.span * 0.16;
    this.G.cameraPosition({ x: p.x, y: p.y - far * 0.25, z: p.z + far }, { x: p.x, y: p.y, z: p.z }, ms);
  }

  turn(on: boolean): void {
    this.turning = on;
    const c = this.G.controls() as { autoRotate?: boolean; autoRotateSpeed?: number };
    c.autoRotate = on; c.autoRotateSpeed = 0.45;
  }

  /** What is on the 3D canvas, read back from the engine's own objects — not from the result it was handed. */
  stats(): Drawn {
    const out: Drawn = { nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0 };
    const data = this.G.graphData();
    for (const d of data.nodes) {
      const m = d.__threeObj?.material;
      if (!m) continue;
      out.nodes++;
      const what = readAlpha(m.opacity);
      if (what === "gone") out.gone++; else if (what === "bright") out.bright++;
    }
    for (const l of data.links) if (l.__lineObj) out.links++;
    for (const el of Array.from(this.labels.children) as HTMLElement[]) {
      if (!el.dataset.i) continue;                                        // a leftover of an earlier result does not count
      if (el.dataset.ring) out.rings++;
      if (el.dataset.ring === "bright") out.ringsBright++;
      if (el.dataset.named) out.named++;
    }
    return out;
  }

  /** Every frame: the rings and names follow their resources across the screen. */
  private frame = (ts: number): void => {
    this.raf = requestAnimationFrame(this.frame);
    this.frames++;
    if (ts - this.fpsAt >= 1000) { this.fps = Math.round((this.frames * 1000) / (ts - this.fpsAt)); this.frames = 0; this.fpsAt = ts; }
    const g = this.g, cam = this.G.camera(), W = window.innerWidth, H = window.innerHeight;
    if (!g) return;
    const at = (x: number, y: number, z: number) => { const v = new this.V3(x, y, z).project(cam); return { x: ((v.x + 1) / 2) * W, y: ((1 - v.y) / 2) * H, out: v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1 }; };

    // the accounts' names float above their regions, in the overview only
    const far = !(this.sc?.path || this.sel !== null);
    this.discs.forEach((d, k) => {
      let el = this.clabels.children[k] as HTMLElement | undefined;
      if (!el) { el = document.createElement("div"); el.className = "c3"; this.clabels.appendChild(el); }
      const p = at(d.x, d.y + d.r * 1.05, 0);
      el.hidden = p.out || !far || !d.label;
      if (el.hidden) return;
      el.style.transform = `translate(${p.x}px,${p.y}px) translate(-50%,-50%)`;
      const text = `${d.label} · ${d.count.toLocaleString("en-US")}`;
      if (el.textContent !== text) el.textContent = text;
    });
    for (let k = this.discs.length; k < this.clabels.children.length; k++) (this.clabels.children[k] as HTMLElement).hidden = true;

    const have = this.labels.children;
    while (have.length < this.list.length) {
      const el = document.createElement("div"); el.className = "l3";
      el.appendChild(document.createElement("i")); el.appendChild(document.createElement("span"));
      this.labels.appendChild(el);
    }
    for (let k = 0; k < have.length; k++) {
      const el = have[k] as HTMLElement, m = this.list[k];
      if (!m) { el.hidden = true; el.dataset.i = el.dataset.ring = el.dataset.named = ""; continue; }
      const n = this.nodes[m.i];
      el.dataset.i = String(m.i); el.dataset.ring = m.ring ? (m.off ? "faint" : "bright") : ""; el.dataset.named = m.named ? "1" : "";
      const p = at(n.x, n.y, n.z);
      if (p.out) { el.hidden = true; continue; }
      el.hidden = false;
      el.style.transform = `translate(${p.x}px,${p.y}px)`;
      const cls = `l3${m.ring ? ` t-${TONE_VAR[m.ring]}` : ""}${m.sel ? " sel" : ""}${m.off ? " off" : ""}${m.gone ? " gone" : ""}${m.named ? "" : " mute"}`;
      if (el.className !== cls) el.className = cls;
      const name = g.nodes[m.i].name;
      if (el.lastChild!.textContent !== name) el.lastChild!.textContent = name;
    }
  };
}
