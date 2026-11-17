import type { WorldGraph } from "./graph";
import type { Layout } from "./layout";
import type { RingTone, Scene } from "./scene";

/** What the 3D view of «全景» needs beyond the flat map: a third coordinate, how strongly each resource is drawn
 *  (and how to read that back from the engine's own objects), and the rings and names laid over the canvas.
 *  All of it follows from the same graph, layout and scene as the flat map — the 3D view decides nothing either. */

const SPREAD = 0.7;

/** −1 … 1 from a resource id: the same number for the same resource on every run (no random numbers). */
function unit(ref: number): number {
  let h = Math.imul(ref ^ 0x9e3779b9, 0x85ebca6b);
  h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
  return ((h >>> 0) / 0xffffffff) * 2 - 1;
}

/** The depth of every resource: what a holder holds sits around the holder's own depth, within the radius of its
 *  circle; what an account holds directly is spread through its type's cloud. A flat disc becomes a ball. */
export function depths(g: WorldGraph, L: Layout): Float32Array {
  const z = new Float32Array(g.nodes.length);
  const holderR = new Map(L.discs.filter((d) => d.kind === "container").map((d) => [d.node, d.r]));
  const cloudR = new Map(L.discs.filter((d) => d.kind === "cloud").map((d) => [`${d.acct}|${d.label}`, d.r]));
  const done = new Uint8Array(g.nodes.length);
  const place = (i: number): number => {
    if (done[i]) return z[i];
    done[i] = 1;                                           // containment has no cycles; this also stops one if a build ever had
    const n = g.nodes[i];
    if (n.parent >= 0) z[i] = place(n.parent) + unit(n.ref) * (holderR.get(n.parent) ?? 1) * SPREAD;
    else if (holderR.has(i)) z[i] = unit(n.ref) * holderR.get(i)! * 0.5;
    else z[i] = unit(n.ref) * (cloudR.get(`${n.acct}|${n.type}`) ?? 1) * SPREAD;
    return z[i];
  };
  for (let i = 0; i < g.nodes.length; i++) place(i);
  return z;
}

/** How strongly a resource is drawn, by opacity. The check reads the opacity back from the engine's materials, so
 *  the three bands — bright, gone, outside the view — must not overlap. */
export const ALPHA = { dim: 0.05, goneDim: 0.12, gone: 0.22, plain: 0.6, ring: 1 } as const;

export function nodeAlpha(sc: Scene, i: number): number {
  const off = !!sc.dim && sc.dim.has(i);
  if (sc.gone.has(i)) return off ? ALPHA.goneDim : ALPHA.gone;          // gone stays «gone» even outside the view
  if (off) return ALPHA.dim;
  return sc.rings.some((r) => r.i === i) ? ALPHA.ring : ALPHA.plain;
}

/** What an opacity read back from the canvas means. */
export function readAlpha(opacity: number): "bright" | "gone" | "dim" {
  return opacity > 0.3 ? "bright" : opacity > 0.09 ? "gone" : "dim";
}

export interface Mark {
  i: number;
  /** the ring's tone; null = a name without a ring */
  ring: RingTone | null;
  /** outside the view: the ring stays, faintly, without its name */
  off: boolean;
  named: boolean;
  sel: boolean;
  gone: boolean;
}

/** The rings and names laid over the 3D canvas as page elements: one per ring, plus the named resources that have
 *  none. In the order of the scene's labels, so what is being looked at comes last and ends up on top. */
export function marks(sc: Scene, sel: number | null): Mark[] {
  const named = new Set(sc.labels);
  const out: Mark[] = sc.rings.map((r) => ({ i: r.i, ring: r.tone, off: r.dim, named: named.has(r.i) && !r.dim, sel: r.i === sel, gone: sc.gone.has(r.i) }));
  const have = new Set(out.map((m) => m.i));
  for (const i of sc.labels) if (!have.has(i)) out.push({ i, ring: null, off: false, named: true, sel: i === sel, gone: sc.gone.has(i) });
  const order = (m: Mark) => sc.labels.indexOf(m.i);
  return out.sort((a, b) => order(a) - order(b));
}
