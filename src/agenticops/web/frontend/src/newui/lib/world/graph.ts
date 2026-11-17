import type { GalaxyGraph, GalaxyHealth, GalaxyHealthRead } from "@/api/types";
import { normalizeHealth } from "@/lib/galaxyHealth";

/** «全景»: the relation graph as the map draws it. GET /api/galaxy/graph sends three kinds of node — accounts,
 *  tag groups and resources — and every relation of the latest build. The map draws resources only: an account is the
 *  label of a region of the map, a tag group is a filter. Nothing is left out silently: `totals` accounts for every
 *  relation of the build — drawn as a line, shown as a cluster, kept as a label or a filter, or dropped. */

export interface WNode {
  /** its place in `nodes` */
  i: number;
  id: string;
  /** cloud_resources.id */
  ref: number;
  name: string;
  type: string;
  acct: number | null;
  /** worst open issue on it; no open issue = unknown, never healthy */
  health: GalaxyHealth;
  /** the latest complete scan no longer saw it */
  absent: boolean;
  /** the resource that holds it (index), -1 when only its account does */
  parent: number;
  /** the tag groups it belongs to (group node ids) */
  groups: string[];
  /** where it is on the map (lib/world/layout) */
  x: number;
  y: number;
}

export interface WEdge {
  /** written a → b (indexes into `nodes`) */
  a: number;
  b: number;
  r: string;
  /** a model inferred it: advisory, drawn dashed, no direction */
  llm: boolean;
  /** containment between two resources: the flat map shows it as the cluster itself */
  contain: boolean;
  ev?: string;
  c?: number;
}

export interface WTotals {
  nodes: number; present: number; gone: number;
  /** every relation the build has */
  relations: number;
  /** between two resources */
  links: number;
  /** of those, drawn as a line on the flat map (everything but containment) */
  lines: number;
  contain: number; rule: number; inferred: number;
  /** containment that is NOT drawn as a circle: a resource in several holders sits in the circle of one (the lowest
   *  id); its other containment relations are lines when it is open */
  containExtra: number;
  /** an account holding a resource — the region label */
  ofAccount: number;
  /** a resource in a tag group — the group filter */
  ofGroup: number;
  /** an end that is not in the build, or a shape the map does not know: counted, never drawn */
  dropped: number;
}

export interface WorldGraph {
  buildId: number | null;
  /** when the build finished: the age of the relations (API time string; null = the server did not say) */
  builtAt: string | null;
  /** when health and «gone» were read — they are not the build's. Moves with every applyHealth */
  healthAt: string | null;
  nodes: WNode[];
  edges: WEdge[];
  byId: Map<string, number>;
  accounts: { id: number; name: string; count: number }[];
  groups: { id: string; name: string; type: string; acct: number | null; count: number }[];
  /** adj[i] = [[j, edge index, out]…] — out: the link is written from i to j */
  adj: [number, number, boolean][][];
  totals: WTotals;
}

const refOf = (id: string): number => Number(id.slice(4));

/** `names` = the accounts' own names by id (the accounts API); the build's account nodes are only «account:1». */
export function indexGraph(payload: GalaxyGraph, names?: ReadonlyMap<number, string>): WorldGraph {
  const kind = new Map(payload.nodes.map((n) => [n.id, n.kind]));
  const nodes: WNode[] = payload.nodes.filter((n) => n.kind === "resource")
    .map((n) => ({ i: 0, id: n.id, ref: refOf(n.id), name: n.name || n.id, type: n.type, acct: n.acct ?? null,
                   health: normalizeHealth(n.health), absent: n.absent === true, parent: -1, groups: [] as string[], x: 0, y: 0 }))
    .sort((a, b) => a.ref - b.ref || a.id.localeCompare(b.id));
  nodes.forEach((n, i) => { n.i = i; });
  const byId = new Map(nodes.map((n) => [n.id, n.i]));

  const edges: WEdge[] = [];
  const totals: WTotals = { nodes: nodes.length, present: 0, gone: 0, relations: payload.edges.length, links: 0, lines: 0, contain: 0,
                            containExtra: 0, rule: 0, inferred: 0, ofAccount: 0, ofGroup: 0, dropped: 0 };
  const parents = new Map<number, number[]>();
  for (const e of payload.edges) {
    const a = byId.get(e.s), b = byId.get(e.t);
    if (a !== undefined && b !== undefined) {
      const llm = e.p === "llm", contain = !llm && e.r === "contains";
      edges.push({ a, b, r: e.r, llm, contain, ...(e.ev ? { ev: e.ev } : {}), ...(typeof e.c === "number" ? { c: e.c } : {}) });
      if (contain) parents.set(b, [...(parents.get(b) ?? []), a]);
    } else if (kind.get(e.s) === "account" && b !== undefined) totals.ofAccount++;
    else if (a !== undefined && kind.get(e.t) === "group") { totals.ofGroup++; nodes[a].groups.push(e.t); }
    else totals.dropped++;
  }
  // one container each: of the resources that hold it, the one with the lowest id — the same one on every build
  for (const [child, held] of parents) nodes[child].parent = held.reduce((p, q) => (nodes[q].ref < nodes[p].ref ? q : p));

  const adj: [number, number, boolean][][] = nodes.map(() => []);
  edges.forEach((e, k) => { adj[e.a].push([e.b, k, true]); adj[e.b].push([e.a, k, false]); });

  totals.gone = nodes.filter((n) => n.absent).length;
  totals.present = nodes.length - totals.gone;
  totals.links = edges.length;
  totals.contain = edges.filter((e) => e.contain).length;
  totals.containExtra = totals.contain - nodes.filter((n) => n.parent >= 0).length;
  totals.inferred = edges.filter((e) => e.llm).length;
  totals.rule = edges.length - totals.inferred;
  totals.lines = edges.length - totals.contain;

  const count = <K,>(keys: K[]) => keys.reduce((m, k) => m.set(k, (m.get(k) ?? 0) + 1), new Map<K, number>());
  const perAccount = count(nodes.map((n) => n.acct)), perGroup = count(nodes.flatMap((n) => n.groups));
  return {
    buildId: payload.build_id, builtAt: payload.built_at ?? null, healthAt: payload.health_at ?? null, nodes, edges, byId, adj, totals,
    accounts: payload.nodes.filter((n) => n.kind === "account")
      .map((n) => ({ id: Number(n.id.slice(5)), name: n.name || n.id }))
      .map((a) => ({ id: a.id, name: names?.get(a.id) ?? a.name, count: perAccount.get(a.id) ?? 0 })).sort((a, b) => a.id - b.id),
    groups: payload.nodes.filter((n) => n.kind === "group")
      .map((n) => ({ id: n.id, name: n.name || n.id, type: n.type, acct: n.acct ?? null, count: perGroup.get(n.id) ?? 0 }))
      .sort((a, b) => a.id.localeCompare(b.id)),
  };
}

/** Health and «gone» read again (GET /api/galaxy/health), put onto the SAME graph: the rings follow the issues
 *  instead of waiting for the next build, and the map keeps its layout and its camera — nothing about the relations
 *  changed. A resource the reading does not list has no open issue. Returns whether anything changed (the scene is
 *  then worked out again); `healthAt` moves either way. A reading of another build is ignored: its ids may mean
 *  other resources. */
export function applyHealth(g: WorldGraph, read: GalaxyHealthRead): boolean {
  if (read.build_id !== g.buildId) return false;
  const gone = new Set(read.absent);
  let changed = false;
  for (const n of g.nodes) {
    const health = normalizeHealth(read.health[n.id]), absent = gone.has(n.id);
    if (health !== n.health || absent !== n.absent) { n.health = health; n.absent = absent; changed = true; }
  }
  g.totals.gone = g.nodes.filter((n) => n.absent).length;
  g.totals.present = g.nodes.length - g.totals.gone;
  g.healthAt = read.at ?? g.healthAt;
  return changed;
}

