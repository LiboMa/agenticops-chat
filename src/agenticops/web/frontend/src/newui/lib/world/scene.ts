import type { WNode, WTotals, WorldGraph } from "./graph";

/** ONE result for the map. Whatever view draws it (flat or 3D) and every number on the page come from here: no view
 *  decides anything by itself. After each draw the view reports what it actually put on its canvas, and `reconcile`
 *  compares — the «数据核对» line says whether the picture matches the data. */

/** What the person asked for. A path beats «only what is around it», which beats the filters; a search highlights
 *  and never hides. */
export interface Ask {
  q: string;
  account: number | null;
  type: string | null;
  /** a tag group's node id */
  group: string | null;
  onlyAbnormal: boolean;
  /** the open resource (index) */
  sel: number | null;
  /** show only what is one link away from `sel` */
  focus: boolean;
  /** the two ends of a path */
  a: number | null;
  b: number | null;
}

export const NO_ASK: Ask = { q: "", account: null, type: null, group: null, onlyAbnormal: false, sel: null, focus: false, a: null, b: null };

/** An item that waits on the person, and the resource it sits on (cloud_resources.id; null = none). */
export interface Waiting { id: string; ref: number | null }

export type RingTone = "critical" | "warning" | "notice";

export interface Scene {
  /** what is outside the view; null = nothing is */
  dim: Set<number> | null;
  /** resources a complete scan no longer lists */
  gone: Set<number>;
  /** present and inside the view */
  shown: number;
  /** every present resource with an open issue wears a ring — outside the view, faintly */
  rings: { i: number; tone: RingTone; dim: boolean }[];
  /** gone resources that still have an open issue: no ring, but counted */
  goneOpen: number;
  hits: number[];
  path: number[] | null;
  around: Set<number> | null;
  /** whose names are drawn; the ones being looked at come last, so they end up on top */
  labels: number[];
  /** what the panel lists: the filters apply, a focus or a path does not; the worst first */
  abnormal: number[];
  /** how the map relates to the queue; null = the queue is not known */
  ties: { ringed: string[]; quiet: string[]; offMap: string[] } | null;
  totals: WTotals;
}

const RANK: Record<string, number> = { critical: 0, warning: 1, notice: 2 };
/** rings are named only when there are few enough for the names to be read */
const NAMED_RINGS_MAX = 12;

const open = (n: WNode): boolean => !n.absent && n.health !== "unknown";

export function around(g: WorldGraph, i: number, hops = 1): Set<number> {
  const seen = new Set([i]);
  let edge = [i];
  for (let h = 0; h < hops; h++) {
    const next: number[] = [];
    for (const k of edge) for (const [j] of g.adj[k]) if (!seen.has(j)) { seen.add(j); next.push(j); }
    edge = next;
  }
  return seen;
}

/** The shortest chain of links from a to b (indexes, ends included); null when there is none within `maxHops`. */
export function path(g: WorldGraph, a: number, b: number, maxHops = 8): number[] | null {
  if (a === b) return null;
  const from = new Map<number, number>([[a, -1]]);
  let edge = [a];
  for (let h = 0; h < maxHops && edge.length; h++) {
    const next: number[] = [];
    for (const i of edge) {
      for (const [j] of [...g.adj[i]].sort((x, y) => x[0] - y[0])) {          // the lowest id first: the same path every time
        if (from.has(j)) continue;
        from.set(j, i);
        if (j === b) {
          const out = [j];
          for (let k = i; k !== -1; k = from.get(k)!) out.push(k);
          return out.reverse();
        }
        next.push(j);
      }
    }
    edge = next;
  }
  return null;
}

function matches(n: WNode, ask: Ask): boolean {
  if (ask.account !== null && n.acct !== ask.account) return false;
  if (ask.type && n.type !== ask.type) return false;
  if (ask.group && !n.groups.includes(ask.group)) return false;
  if (ask.onlyAbnormal && !open(n)) return false;
  return true;
}

/** By a part of the name or the type, by the resource's own id, or by the number of an item that waits on the
 *  person (I#12). What has something open comes first, then names that start with the text. */
export function search(g: WorldGraph, q: string, waiting: Waiting[] | null, limit = 8): number[] {
  const text = q.trim().toLowerCase();
  if (!text) return [];
  const item = text.replace("#", "").toUpperCase();
  const onItem = new Set((waiting ?? []).filter((w) => w.id === item && w.ref !== null).map((w) => w.ref));
  const hit = (n: WNode) => n.name.toLowerCase().includes(text) || n.type.toLowerCase().includes(text) || n.id === text || onItem.has(n.ref);
  const first = (n: WNode) => (n.name.toLowerCase().startsWith(text) ? 0 : 1);
  return g.nodes.filter(hit)
    .sort((x, y) => Number(!open(x)) - Number(!open(y)) || (RANK[x.health] ?? 3) - (RANK[y.health] ?? 3) || first(x) - first(y) || x.i - y.i)
    .slice(0, limit).map((n) => n.i);
}

export function scene(g: WorldGraph, ask: Ask, waiting: Waiting[] | null): Scene {
  const way = ask.a !== null && ask.b !== null ? path(g, ask.a, ask.b) : null;
  const waySet = way ? new Set(way) : null;
  const near = !waySet && ask.focus && ask.sel !== null ? around(g, ask.sel) : null;
  const filtered = ask.account !== null || !!ask.type || !!ask.group || ask.onlyAbnormal;

  let dim: Set<number> | null = null;
  if (waySet || near || filtered) {
    dim = new Set();
    for (const n of g.nodes) if (!(waySet ? waySet.has(n.i) : near ? near.has(n.i) : matches(n, ask))) dim.add(n.i);
  }
  const gone = new Set(g.nodes.filter((n) => n.absent).map((n) => n.i));
  const ringed = g.nodes.filter(open);
  const rings = ringed.map((n) => ({ i: n.i, tone: n.health as RingTone, dim: !!dim && dim.has(n.i) }));
  const hits = search(g, ask.q, waiting);

  const labels = new Map<number, true>();
  const bright = rings.filter((r) => !r.dim);
  if (bright.length <= NAMED_RINGS_MAX) for (const r of bright) labels.set(r.i, true);
  for (const i of hits) labels.set(i, true);
  for (const i of way ?? []) labels.set(i, true);
  for (const i of [ask.b, ask.a, ask.sel]) if (i !== null) { labels.delete(i); labels.set(i, true); }

  let shown = 0;
  for (const n of g.nodes) if (!gone.has(n.i) && !(dim && dim.has(n.i))) shown++;

  const byRef = new Map(g.nodes.map((n) => [n.ref, n]));
  const ties = waiting === null ? null : {
    ringed: waiting.filter((w) => w.ref !== null && byRef.has(w.ref) && open(byRef.get(w.ref)!)).map((w) => w.id),
    quiet: waiting.filter((w) => w.ref !== null && byRef.has(w.ref) && !open(byRef.get(w.ref)!)).map((w) => w.id),
    offMap: waiting.filter((w) => w.ref === null || !byRef.has(w.ref)).map((w) => w.id),
  };

  return {
    dim, gone, shown, rings, hits, path: way, around: near, labels: [...labels.keys()], ties, totals: g.totals,
    goneOpen: g.nodes.filter((n) => n.absent && n.health !== "unknown").length,
    abnormal: ringed.filter((n) => matches(n, ask)).sort((x, y) => (RANK[x.health] ?? 3) - (RANK[y.health] ?? 3) || x.i - y.i).map((n) => n.i),
  };
}

/** What a view reports it drew. */
export interface Drawn { nodes: number; bright: number; gone: number; rings: number; ringsBright: number; links: number; named: number }

export type View = "2d" | "3d";

/** What a view must have on its canvas for this result. The flat map shows containment as the circles themselves,
 *  so its lines are every link but those; the 3D view has no circles and draws every link. */
export function expected(sc: Scene, view: View = "2d"): Drawn {
  return { nodes: sc.totals.nodes, bright: sc.shown, gone: sc.gone.size, rings: sc.rings.length, ringsBright: sc.rings.filter((r) => !r.dim).length,
           links: view === "3d" ? sc.totals.links : sc.totals.lines, named: sc.labels.length };
}

/** The check: what the view says it drew against what the data says. [] = they agree. */
export function reconcile(sc: Scene, drawn: Drawn, view: View = "2d"): { what: keyof Drawn; want: number; got: number }[] {
  const want = expected(sc, view);
  return (Object.keys(want) as (keyof Drawn)[]).filter((k) => drawn[k] !== want[k]).map((k) => ({ what: k, want: want[k], got: drawn[k] }));
}
