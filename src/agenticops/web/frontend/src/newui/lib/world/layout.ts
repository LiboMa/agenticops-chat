import type { WorldGraph } from "./graph";

/** Where each resource sits on the map. The graph API sends no coordinates, so the map lays the build out itself —
 *  by containment, which is the one structure every resource has: an account holds resources, a VPC holds subnets
 *  and security groups, a subnet holds instances. Each holder is a circle with what it holds inside it; what an
 *  account holds directly is gathered into one cloud per resource type.
 *
 *  The layout is a picture, not a topology: distance means nothing. What it guarantees is that the same build always
 *  gives the same picture (no random numbers, no simulation — every list is sorted by resource id first). */

export interface Disc {
  /** account = a region of the map · container = a resource and what it holds · cloud = one type of resource an
   *  account holds directly */
  kind: "account" | "container" | "cloud";
  x: number;
  y: number;
  r: number;
  /** the account's name, the container's name, or the cloud's resource type */
  label: string;
  /** the container resource (index); -1 otherwise */
  node: number;
  acct: number | null;
  /** how many resources are inside */
  count: number;
}

export interface Layout { discs: Disc[]; bounds: { x0: number; y0: number; x1: number; y1: number } }

const STEP = 1;                    // the distance between neighbouring dots
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const PAD = 1.2;                   // the room between two circles of one level

/** A piece of the picture before it has a place: its radius, and how to put its content down around a centre. */
interface Piece { r: number; put: (cx: number, cy: number) => void; order: number }

/** Circles packed around the origin: the largest first, each at the free spot nearest the centre. Deterministic.
 *  `pinFirst` keeps circle 0 at the origin whatever its size (a holder stays in the middle of what it holds). */
function pack(radii: number[], pinFirst = false): { x: number; y: number }[] {
  const at: { x: number; y: number }[] = radii.map(() => ({ x: 0, y: 0 }));
  const bySize = (a: number, b: number) => radii[b] - radii[a] || a - b;
  const order = pinFirst ? [0, ...radii.map((_, i) => i).slice(1).sort(bySize)] : radii.map((_, i) => i).sort(bySize);
  const placed: number[] = [];
  for (const i of order) {
    const r = radii[i];
    if (placed.length) {
      const free = (x: number, y: number) => placed.every((j) => Math.hypot(x - at[j].x, y - at[j].y) >= r + radii[j] + PAD);
      const stride = Math.max(r * 0.35, 0.6);
      search: for (let d = stride; ; d += stride) {
        const n = Math.max(12, Math.ceil((2 * Math.PI * d) / stride));
        for (let k = 0; k < n; k++) {
          const a = (2 * Math.PI * k) / n, x = d * Math.cos(a), y = d * Math.sin(a);
          if (free(x, y)) { at[i] = { x, y }; break search; }
        }
      }
    }
    placed.push(i);
  }
  return at;
}

const reach = (at: { x: number; y: number }[], radii: number[]) => at.reduce((m, p, i) => Math.max(m, Math.hypot(p.x, p.y) + radii[i]), 0);

export function layout(g: WorldGraph): Layout {
  const discs: Disc[] = [];
  if (!g.nodes.length) return { discs, bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
  const kids: number[][] = g.nodes.map(() => []);
  g.nodes.forEach((n) => { if (n.parent >= 0) kids[n.parent].push(n.i); });      // nodes are in id order, so each list is too
  const size = (i: number): number => kids[i].reduce((s, k) => s + size(k), 1);

  /** dots on a sunflower spiral around a centre; `from` = 1 leaves the centre itself free for the holder */
  const spiral = (ids: number[], from: number) => ({
    r: STEP * Math.sqrt(ids.length + from) + STEP * 0.5,
    put: (cx: number, cy: number) => ids.forEach((i, k) => {
      const d = STEP * Math.sqrt(k + from), a = k * GOLDEN;
      g.nodes[i].x = cx + d * Math.cos(a);
      g.nodes[i].y = cy + d * Math.sin(a);
    }),
  });

  /** a resource and everything it holds */
  const container = (i: number): Piece => {
    const leaves = kids[i].filter((k) => !kids[k].length), holders = kids[i].filter((k) => kids[k].length);
    const core = spiral(leaves, 1), inner = holders.map(container);
    // the holder and its own leaves stay in the middle; what holds others is packed around them
    const radii = [core.r, ...inner.map((p) => p.r)], at = pack(radii, true), r = reach(at, radii) + STEP * 0.5;
    return {
      r, order: g.nodes[i].ref,
      put: (cx, cy) => {
        g.nodes[i].x = cx; g.nodes[i].y = cy;
        core.put(cx, cy);
        inner.forEach((p, k) => p.put(cx + at[k + 1].x, cy + at[k + 1].y));
        discs.push({ kind: "container", x: cx, y: cy, r, label: g.nodes[i].name, node: i, acct: g.nodes[i].acct, count: size(i) });
      },
    };
  };

  /** an account: the resources it holds that hold others, and one cloud per type for the rest */
  const account = (acct: number | null, name: string): Piece => {
    const top = g.nodes.filter((n) => n.acct === acct && n.parent < 0).map((n) => n.i);
    const holders = top.filter((i) => kids[i].length).map(container);
    const byType = new Map<string, number[]>();
    for (const i of top.filter((k) => !kids[k].length)) byType.set(g.nodes[i].type, [...(byType.get(g.nodes[i].type) ?? []), i]);
    const types = [...byType.keys()].sort();
    const clouds = types.map((type) => ({ type, ids: byType.get(type)!, ...spiral(byType.get(type)!, 0.5) }));
    const radii = [...clouds.map((c) => c.r), ...holders.map((h) => h.r)], at = pack(radii), r = reach(at, radii) + STEP * 2;
    return {
      r, order: acct ?? Infinity,
      put: (cx, cy) => {
        discs.push({ kind: "account", x: cx, y: cy, r, label: name, node: -1, acct, count: g.nodes.filter((n) => n.acct === acct).length });
        clouds.forEach((c, k) => {
          c.put(cx + at[k].x, cy + at[k].y);
          discs.push({ kind: "cloud", x: cx + at[k].x, y: cy + at[k].y, r: c.r, label: c.type, node: -1, acct, count: c.ids.length });
        });
        holders.forEach((h, k) => h.put(cx + at[clouds.length + k].x, cy + at[clouds.length + k].y));
      },
    };
  };

  const names = new Map(g.accounts.map((a) => [a.id, a.name] as const));
  const ids = [...new Set(g.nodes.map((n) => n.acct))].sort((a, b) => (a ?? Infinity) - (b ?? Infinity));
  const regions = ids.map((id) => account(id, id === null ? "" : names.get(id) ?? `#${id}`));
  const radii = regions.map((p) => p.r), at = pack(radii);
  regions.forEach((p, k) => p.put(at[k].x, at[k].y));

  // regions first (in account order), then clouds and containers in the order they were put down
  discs.sort((a, b) => Number(b.kind === "account") - Number(a.kind === "account"));
  const bounds = discs.filter((d) => d.kind === "account").reduce((b, d) => ({
    x0: Math.min(b.x0, d.x - d.r), y0: Math.min(b.y0, d.y - d.r), x1: Math.max(b.x1, d.x + d.r), y1: Math.max(b.y1, d.y + d.r),
  }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
  return { discs, bounds };
}
