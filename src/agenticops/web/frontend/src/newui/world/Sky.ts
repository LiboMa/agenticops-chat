import type { WorldGraph } from "../lib/world/graph";
import type { Disc, Layout } from "../lib/world/layout";
import { flow } from "../lib/world/relations";
import type { Drawn, RingTone, Scene } from "../lib/world/scene";

/** The flat star map: every resource is a star, the ones with something open wear a ring. This file decides nothing:
 *  WHERE things are comes from lib/world/layout, WHAT to show from lib/world/scene. It draws the result it is handed
 *  and counts what it drew while drawing (`stats`), so the lens can check the picture against the data.
 *  Drawing is batched — a handful of paths per frame, not one per star. */

const LABEL = "12px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif";
const TAU = Math.PI * 2;
const TONE_VAR: Record<RingTone, "red" | "amber" | "mint"> = { critical: "red", warning: "amber", notice: "mint" };
const NONE: Drawn = { nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0 };

interface Colors { ink2: string; star: string; amber: string; mint: string; red: string; dim: string; chalk: string; faint: string }

export interface SkyMode {
  /** the lens is «全景»: full brightness, the person's camera; otherwise the map is a faint backdrop */
  world: boolean;
  /** how much of the canvas the panels cover on the left and the right (px) — the map is fitted into what is left */
  inset: { left: number; right: number; top: number; bottom: number };
  /** the 3D view is showing instead: this canvas draws nothing */
  off?: boolean;
}

export class Sky {
  fps = 0;
  drawMs = 0;
  private cx: CanvasRenderingContext2D;
  private W = 0;
  private H = 0;
  private dpr = 1;
  private colors: Colors = { ink2: "#000", star: "255,255,255", amber: "#fb2", mint: "#5ec", red: "#f77", dim: "#aaa", chalk: "#eee", faint: "#888" };
  private g: WorldGraph | null = null;
  private discs: Disc[] = [];
  private bounds: Layout["bounds"] = { x0: -1, y0: -1, x1: 1, y1: 1 };
  private sx = new Float32Array(0);
  private sy = new Float32Array(0);
  private on = new Uint8Array(0);
  private sc: Scene | null = null;
  /** the graph `sc` was worked out on: a result is drawn only on its own graph */
  private scOf: WorldGraph | null = null;
  private sel: number | null = null;
  private mode: SkyMode = { world: false, inset: { left: 0, right: 0, top: 0, bottom: 0 } };
  private cam = { x: 0, y: 0, z: 1, tx: 0, ty: 0, tz: 1 };
  private free = false;
  private drawn: Drawn = { ...NONE };
  private raf = 0;
  private frames = 0;
  private fpsAt = 0;
  private running = false;
  private asleep = true;
  private readonly still: boolean;
  private readonly onResize = () => this.resize();

  constructor(private canvas: HTMLCanvasElement, private root: HTMLElement) {
    this.cx = canvas.getContext("2d")!;
    this.still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.recolor();
    this.resize();
    window.addEventListener("resize", this.onResize);
  }

  dispose(): void {
    this.stop();
    window.removeEventListener("resize", this.onResize);
  }

  /** The colours are the page's own (they change with day / night). */
  recolor(): void {
    const cs = getComputedStyle(this.root), v = (n: string) => cs.getPropertyValue(n).trim();
    this.colors = { ink2: v("--ink2"), star: v("--star"), amber: v("--amber"), mint: v("--mint"), red: v("--red"), dim: v("--dim"), chalk: v("--chalk"), faint: v("--faint") };
    this.kick();
  }

  resize(): void {
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.W = this.canvas.clientWidth;
    this.H = this.canvas.clientHeight;
    this.canvas.width = Math.max(1, Math.round(this.W * this.dpr));
    this.canvas.height = Math.max(1, Math.round(this.H * this.dpr));
    this.aim();
    this.kick();
  }

  setGraph(g: WorldGraph | null, layout: Layout | null): void {
    this.g = g;
    this.discs = layout?.discs ?? [];
    this.bounds = layout?.bounds ?? { x0: -1, y0: -1, x1: 1, y1: 1 };
    const n = g?.nodes.length ?? 0;
    this.sx = new Float32Array(n); this.sy = new Float32Array(n); this.on = new Uint8Array(n);
    this.free = false;
    this.aim(true);
    this.kick();
  }

  /** Hand over what to show (the one shared result), which resource is open, and the graph both were worked out on.
   *  The result is drawn only while that graph is the one on the canvas: the lens hands its result over before the
   *  data layer hands over the graph (a child's effect runs first), and a result of an older build must never be
   *  drawn on a newer one — its indexes would mean other resources. */
  apply(sc: Scene | null, sel: number | null, of: WorldGraph | null): void { this.sc = sc; this.sel = sel; this.scOf = of; this.kick(); }

  setMode(mode: SkyMode): void {
    const turned = mode.world !== this.mode.world;
    this.mode = mode;
    if (turned) this.free = false;
    this.aim();
    this.kick();
  }

  /** What the last frame put on the canvas, counted while drawing. */
  stats(): Drawn { return this.drawn; }

  // ── the camera ────────────────────────────────────────────────────────────
  /** px per map unit at which the whole map fits into the free part of the canvas */
  private fit(): number {
    const { left, right, top, bottom } = this.mode.world ? this.mode.inset : { left: 0, right: 0, top: 0, bottom: 0 };
    const w = Math.max(120, this.W - left - right), h = Math.max(120, this.H - top - bottom);
    return Math.min(w / (this.bounds.x1 - this.bounds.x0), h / (this.bounds.y1 - this.bounds.y0)) * 0.94;
  }

  /** Where the camera should be: the whole map, unless the person moved it. */
  private aim(jump = false): void {
    if (!(this.mode.world && this.free)) {
      const { left, right, top, bottom } = this.mode.world ? this.mode.inset : { left: 0, right: 0, top: 0, bottom: 0 };
      this.cam.tz = this.fit() * (this.mode.world ? 1 : 1.12);
      const cx = (this.bounds.x0 + this.bounds.x1) / 2, cy = (this.bounds.y0 + this.bounds.y1) / 2;
      // the middle of the free part of the canvas, not of the canvas
      this.cam.tx = cx - (left - right) / 2 / this.cam.tz;
      this.cam.ty = cy - (top - bottom) / 2 / this.cam.tz;
    }
    if (jump) { this.cam.x = this.cam.tx; this.cam.y = this.cam.ty; this.cam.z = this.cam.tz; }
  }

  flyTo(i: number): void {
    const n = this.g?.nodes[i];
    if (!n) return;
    this.free = true;
    this.cam.tz = Math.max(this.cam.tz, this.fit() * 3.2);
    const { left, right } = this.mode.inset;
    this.cam.tx = n.x - (left - right) / 2 / this.cam.tz;
    this.cam.ty = n.y;
  }

  home(): void { this.free = false; this.aim(); }

  /** Zoom around a point on screen (the wheel, a pinch). */
  zoomAt(px: number, py: number, factor: number): void {
    const z0 = this.cam.tz, wx = this.cam.tx + (px - this.W / 2) / z0, wy = this.cam.ty + (py - this.H / 2) / z0;
    const fit = this.fit();
    this.cam.tz = Math.max(fit * 0.6, Math.min(fit * 40, z0 * factor));
    this.cam.tx = wx - (px - this.W / 2) / this.cam.tz;
    this.cam.ty = wy - (py - this.H / 2) / this.cam.tz;
    this.free = true;
  }

  panBy(dx: number, dy: number): void {
    this.cam.tx -= dx / this.cam.z; this.cam.ty -= dy / this.cam.z;
    this.cam.x = this.cam.tx; this.cam.y = this.cam.ty;
    this.free = true;
  }

  /** The resource nearest to a point on screen, within 16 px; one that wears a ring wins over a plain star. */
  pick(px: number, py: number): number | null {
    if (!this.g) return null;
    const ringed = new Set(this.scOf === this.g ? this.sc?.rings.map((r) => r.i) : []);
    let best: number | null = null, bd = 16 * 16;
    for (let i = 0; i < this.sx.length; i++) {
      if (!this.on[i]) continue;
      let d = (this.sx[i] - px) ** 2 + (this.sy[i] - py) ** 2;
      if (ringed.has(i)) d *= 0.35;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  // ── drawing ───────────────────────────────────────────────────────────────
  start(): void { this.running = true; this.kick(); }
  stop(): void { this.running = false; this.asleep = true; cancelAnimationFrame(this.raf); }

  /** Draw again. «全景» draws every frame (the stars twinkle, the dots run); a backdrop draws until the camera has
   *  settled and then sleeps until something changes — a page nobody is looking at should not cost a frame loop. */
  private kick(): void {
    if (!this.running || !this.asleep) return;
    this.asleep = false;
    this.raf = requestAnimationFrame(this.draw);
  }

  private next(): void {
    const cam = this.cam, moving = Math.abs(cam.tx - cam.x) + Math.abs(cam.ty - cam.y) > 0.01 || Math.abs(cam.tz - cam.z) > cam.tz * 0.002;
    if (!this.mode.world && !moving) { this.asleep = true; return; }
    this.raf = requestAnimationFrame(this.draw);
  }

  private rgba(alpha: number): string { return `rgba(${this.colors.star},${alpha})`; }

  private label(i: number, text: string, struck: boolean): void {
    const cx = this.cx, x = this.sx[i], y = this.sy[i];
    cx.font = LABEL;
    const w = cx.measureText(text).width;
    cx.globalAlpha = 0.78; cx.fillStyle = this.colors.ink2; cx.fillRect(x + 12, y - 9, w + 10, 18);
    cx.globalAlpha = 1; cx.fillStyle = struck ? this.colors.dim : this.colors.chalk; cx.fillText(text, x + 17, y + 4);
    if (struck) { cx.strokeStyle = this.colors.dim; cx.lineWidth = 1; cx.beginPath(); cx.moveTo(x + 16, y); cx.lineTo(x + 18 + w, y); cx.stroke(); }
  }

  private draw = (ts: number): void => {
    if (!this.running) return;
    const t0 = performance.now(), t = ts / 1000, cx = this.cx, cam = this.cam, W = this.W, H = this.H, g = this.g;
    this.frames++;
    if (ts - this.fpsAt >= 1000) { this.fps = Math.round((this.frames * 1000) / (ts - this.fpsAt)); this.frames = 0; this.fpsAt = ts; }
    cam.x += (cam.tx - cam.x) * 0.12; cam.y += (cam.ty - cam.y) * 0.12; cam.z += (cam.tz - cam.z) * 0.12;
    cx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    cx.clearRect(0, 0, W, H);
    const D: Drawn = { ...NONE };
    if (!g || !g.nodes.length || this.mode.off) { this.drawn = D; this.next(); return; }

    const world = this.mode.world, z = cam.z, ox = W / 2, oy = H / 2, N = g.nodes, sx = this.sx, sy = this.sy, on = this.on;
    const mine = this.scOf === g, R = mine ? this.sc : null, sel = mine ? this.sel : null;
    const faint = R?.dim ?? null, gone = R?.gone ?? null, C = this.colors;
    for (let i = 0; i < N.length; i++) {
      const x = ox + (N[i].x - cam.x) * z, y = oy + (N[i].y - cam.y) * z;
      sx[i] = x; sy[i] = y; on[i] = x > -20 && x < W + 20 && y > -20 && y < H + 20 ? 1 : 0;
    }

    // the regions: an account's outline and name; a holder's circle once it is big enough to read
    cx.lineWidth = 1; cx.font = LABEL; cx.textAlign = "center";
    for (const d of this.discs) {
      const r = d.r * z, x = ox + (d.x - cam.x) * z, y = oy + (d.y - cam.y) * z;
      if (x + r < 0 || x - r > W || y + r < 0 || y - r > H) continue;
      if (d.kind === "account") {
        cx.strokeStyle = this.rgba(world ? 0.16 : 0.07); cx.beginPath(); cx.arc(x, y, r, 0, TAU); cx.stroke();
        if (world && d.label) { cx.fillStyle = C.dim; cx.globalAlpha = 0.9; cx.fillText(`${d.label} · ${d.count.toLocaleString("en-US")}`, x, Math.max(14, y - r - 6)); cx.globalAlpha = 1; }
      } else if (world && d.kind === "container" && r > 14) {
        cx.strokeStyle = this.rgba(0.1); cx.beginPath(); cx.arc(x, y, r, 0, TAU); cx.stroke();
      } else if (world && d.kind === "cloud" && r > 34) {
        cx.fillStyle = C.faint; cx.globalAlpha = 0.85; cx.fillText(`${d.label} · ${d.count}`, x, y - r - 4); cx.globalAlpha = 1;
      }
    }
    cx.textAlign = "start";

    // links: rule, model-inferred (dashed), and those outside what is being looked at. Containment is the circles.
    const P = [new Path2D(), new Path2D(), new Path2D()], E = g.edges;
    for (let k = 0; k < E.length; k++) {
      const e = E[k];
      if (e.contain) continue;
      D.links++;
      if (!on[e.a] && !on[e.b]) continue;
      const p = faint && (faint.has(e.a) || faint.has(e.b)) ? P[2] : e.llm ? P[1] : P[0];
      p.moveTo(sx[e.a], sy[e.a]); p.lineTo(sx[e.b], sy[e.b]);
    }
    cx.lineWidth = 1;
    cx.strokeStyle = this.rgba(world ? 0.2 : 0.06); cx.stroke(P[0]);
    if (world) { cx.setLineDash([3, 4]); cx.strokeStyle = this.rgba(0.2); cx.stroke(P[1]); cx.setLineDash([]); cx.strokeStyle = this.rgba(0.035); cx.stroke(P[2]); }
    else { cx.strokeStyle = this.rgba(0.045); cx.stroke(P[1]); }

    // stars: six twinkle groups, each one path; outside the view one faint path; the gone ones hollow
    const dot = Math.max(1.1, Math.min(4.2, 0.34 * z)), B = Array.from({ length: 6 }, () => new Path2D()), F = new Path2D(), G = new Path2D(), G2 = new Path2D();
    for (let i = 0; i < N.length; i++) {
      const isGone = !!gone && gone.has(i), off = !!faint && faint.has(i);
      D.nodes++;
      if (isGone) D.gone++; else if (!off) D.bright++;
      if (!on[i]) continue;
      if (isGone) { const p = off ? G2 : G; p.moveTo(sx[i] + 3.2, sy[i]); p.arc(sx[i], sy[i], 3.2, 0, TAU); continue; }
      const p = off ? F : B[i % 6];
      p.moveTo(sx[i] + dot, sy[i]); p.arc(sx[i], sy[i], dot, 0, TAU);
    }
    for (let b = 0; b < 6; b++) {
      const tw = this.still ? 0.75 : 0.55 + 0.35 * Math.sin(t * 1.3 + b * 1.047);
      cx.fillStyle = this.rgba((world ? 0.8 : 0.3) * tw); cx.fill(B[b]);
    }
    if (faint) { cx.fillStyle = this.rgba(0.1); cx.fill(F); }
    cx.setLineDash([2, 2]); cx.lineWidth = 1; cx.strokeStyle = this.rgba(world ? 0.7 : 0.25); cx.stroke(G); cx.strokeStyle = this.rgba(0.2); cx.stroke(G2); cx.setLineDash([]);

    // the open resource's own links — containment too; a dot runs along each one the way a fault would travel
    const lit = world ? sel : null;
    if (lit !== null && lit < N.length && !R?.path) {
      cx.strokeStyle = C.chalk; cx.globalAlpha = 0.75; cx.lineWidth = 1.2;
      for (const [j, k] of g.adj[lit]) { cx.setLineDash(E[k].llm ? [3, 4] : []); cx.beginPath(); cx.moveTo(sx[lit], sy[lit]); cx.lineTo(sx[j], sy[j]); cx.stroke(); }
      cx.setLineDash([]); cx.globalAlpha = 1;
      cx.fillStyle = C.chalk;
      for (const [j] of g.adj[lit]) { cx.beginPath(); cx.arc(sx[j], sy[j], 2.4, 0, TAU); cx.fill(); }
      if (!this.still) g.adj[lit].forEach(([j, k, out], n) => {
        const way = flow({ r: E[k].r, p: E[k].llm ? "llm" : "rule" });
        if (way === "none") return;                                     // no known direction: no dot
        const u = (t * 0.45 + n * 0.37) % 1;
        cx.fillStyle = C.mint;
        // from this resource outwards, towards it — or, for a two-way relation, one dot each way
        for (const outward of way === "both" ? [true, false] : [(way === "forward") === out]) {
          const [fx, fy, tx, ty] = outward ? [sx[lit], sy[lit], sx[j], sy[j]] : [sx[j], sy[j], sx[lit], sy[lit]];
          cx.beginPath(); cx.arc(fx + (tx - fx) * u, fy + (ty - fy) * u, 2.2, 0, TAU); cx.fill();
        }
      });
    }
    // a path between two resources: how they are linked — not a claim that a fault travels along it
    if (world && R?.path) {
      cx.strokeStyle = C.mint; cx.lineWidth = 2.2; cx.beginPath();
      R.path.forEach((i, k) => { if (k) cx.lineTo(sx[i], sy[i]); else cx.moveTo(sx[i], sy[i]); });
      cx.stroke();
      cx.fillStyle = C.chalk;
      for (const i of R.path) { cx.beginPath(); cx.arc(sx[i], sy[i], 3, 0, TAU); cx.fill(); }
    }
    // resources with something open
    if (R) for (const r of R.rings) {
      const i = r.i, c = C[TONE_VAR[r.tone]], pulse = this.still || !world ? 1 : 1 + 0.3 * Math.sin(t * 2.4 + i);
      D.rings++;
      if (!r.dim) D.ringsBright++;
      if (!on[i]) continue;
      cx.strokeStyle = c; cx.globalAlpha = r.dim ? 0.18 : world ? 0.55 : 0.3; cx.lineWidth = 1.2;
      cx.beginPath(); cx.arc(sx[i], sy[i], 7 * pulse, 0, TAU); cx.stroke();
      cx.globalAlpha = r.dim ? 0.25 : world ? 1 : 0.55; cx.fillStyle = c;
      cx.beginPath(); cx.arc(sx[i], sy[i], Math.max(2.6, dot + 0.6), 0, TAU); cx.fill();
      cx.globalAlpha = 1;
    }
    if (world && R) {
      for (const i of R.hits) { cx.strokeStyle = C.chalk; cx.lineWidth = 1.4; cx.beginPath(); cx.arc(sx[i], sy[i], 7, 0, TAU); cx.stroke(); }
      if (sel !== null && sel < N.length) { cx.strokeStyle = C.chalk; cx.lineWidth = 2; cx.beginPath(); cx.arc(sx[sel], sy[sel], 11, 0, TAU); cx.stroke(); }
      for (const i of R.labels) { D.named++; this.label(i, N[i].name, !!gone && gone.has(i)); }
    }
    this.drawn = D;
    this.drawMs += (performance.now() - t0 - this.drawMs) * 0.05;       // what one frame costs, smoothed
    this.next();
  };
}
