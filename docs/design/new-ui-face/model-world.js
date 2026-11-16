/* new-UI-face — the «全景» lens without a screen: the star map's layout and the questions asked of it. No DOM, no canvas.
   The layout is schematic (seeded random numbers), not a real topology; the rules are real:
     · health has four values and «no open issue» is «unknown», never «healthy»;
     · the past is shown as it was: what was open at that hour, not what is open now. */
(function(){
"use strict";
const NF = window.NF;

NF.TYPES = [
  {id: "compute", pre: ["i-", "asg-", "fn-"]}, {id: "network", pre: ["sg-", "subnet-", "elb-", "rtb-"]}, {id: "database", pre: ["db-", "cache-"]},
  {id: "storage", pre: ["vol-", "bkt-"]}, {id: "container", pre: ["pod-", "svc-", "deploy-"]}, {id: "security", pre: ["role-", "key-", "cert-"]},
];
const PROFILE = {general: [30, 25, 8, 15, 7, 15], data: [15, 12, 35, 30, 0, 8], k8s: [10, 15, 0, 0, 70, 5], edge: [0, 60, 0, 15, 0, 25]};   // weights in NF.TYPES order
const CLOSED = ["fixed", "done", "closed", "cancelled"];
const TONE = {red: "critical", amber: "warning"};

/* The map: {nodes, edges, hot}. node = {i, x, y, cl, r, ph, b, name, type, account, region, hot?}; edge = [a, b, flags]
   (flags: 1 = between clusters, 2 = inferred by a model — advisory, drawn dashed, 4 = containment — the flat map shows it as the
   cluster itself and draws the line only for the selected resource). opts.count scales every cluster. */
NF.buildSky = (seed, opts = {}) => {
  let rs = 20261110;
  const R = () => { rs |= 0; rs = rs + 0x6D2B79F5 | 0; let t = Math.imul(rs ^ rs >>> 15, 1 | rs); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const gauss = () => (R() + R() + R() + R() - 2) / 2;
  const C = seed.clusters, total = C.reduce((a, c) => a + c.n, 0), want = opts.count || total;
  const sizes = C.map(c => Math.round(c.n * want / total)); sizes[0] += want - sizes.reduce((a, b) => a + b, 0);
  const nodes = [], edges = [], hot = [];
  C.forEach((c, ci) => {
    const w = PROFILE[c.profile] || PROFILE.general, sum = w.reduce((a, b) => a + b, 0);
    for (let k = 0; k < sizes[ci]; k++){
      let pickT = R() * sum, ti = 0; while (pickT >= w[ti]){ pickT -= w[ti]; ti++; }
      const ty = NF.TYPES[ti], i = nodes.length;
      nodes.push({i, x: c.cx + gauss() * c.sp * 1.5, y: c.cy + gauss() * c.sp * 1.5, cl: ci, r: .45 + R() * .8, ph: R() * 6.28, b: i % 6,
        name: ty.pre[Math.floor(R() * ty.pre.length)] + (0x1000 + i).toString(16), type: ty.id, account: c.account, region: c.region});
    }
  });
  seed.hot.forEach(h0 => {                          // named resources keep apart inside their cluster
    const h = {...h0}, c = C[h.cl];
    const pool = nodes.filter(n => n.cl === h.cl && !n.hot && Math.hypot(n.x - c.cx, n.y - c.cy) < c.sp * 1.5), named = nodes.filter(n => n.cl === h.cl && n.hot);
    const score = n => named.length ? Math.min(...named.map(m => Math.hypot(n.x - m.x, (n.y - m.y) * 2.2))) : -Math.hypot(n.x - (c.cx - c.sp * .5), n.y - (c.cy - c.sp * .6));
    const n = pool.reduce((a, b) => score(b) > score(a) ? b : a);
    n.name = h.name; n.type = h.type || n.type; n.r = 2.4; n.hot = h; h.node = n; hot.push(h);
  });
  const start = []; let at = 0; sizes.forEach(s => { start.push(at); at += s; });
  sizes.forEach((size, ci) => {                     // each node joins its two nearest neighbours in the same cluster
    const lo = start[ci], hi = lo + size;
    for (let i = lo; i < hi; i++){
      let j1 = -1, d1 = Infinity, j2 = -1, d2 = Infinity; const a = nodes[i];
      for (let j = lo; j < hi; j++){ if (j === i) continue; const b = nodes[j], d = (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
        if (d < d1){ j2 = j1; d2 = d1; j1 = j; d1 = d; } else if (d < d2){ j2 = j; d2 = d; } }
      [j1, j2].forEach(j => { if (j > i) edges.push([i, j, R() < .08 ? 2 : 0]); });
    }
  });
  const edge = C.length - 1;                        // a few links from the shared cluster to the others
  for (let k = 0; k < 10; k++){ const a = start[edge] + Math.floor(R() * sizes[edge]), b = Math.floor(R() * start[edge]); edges.push([a, b, 1]); }
  /* Containment (flag 4): every cluster has one root (a VPC, an EKS cluster) and a sub-container per ~45 resources (a subnet,
     a namespace) on a ring around it; each resource belongs to the nearest one, and the roots meet in the shared cluster. This is what makes two
     resources a few links apart, as they are in a real account. No random numbers: the layout above stays as it was. */
  const roots = [];
  sizes.forEach((size, ci) => {
    const lo = start[ci], hi = lo + size, c = C[ci], k8s = c.profile === "k8s", free = []; for (let i = lo; i < hi; i++) if (!nodes[i].hot) free.push(nodes[i]);
    const d2 = (a, x, y) => (a.x - x) ** 2 + (a.y - y) ** 2;
    const root = free.reduce((a, b) => d2(b, c.cx, c.cy) < d2(a, c.cx, c.cy) ? b : a); roots.push(root);
    root.name = (k8s ? "eks-" : "vpc-") + (0x1000 + root.i).toString(16); root.type = k8s ? "container" : "network"; root.r = 1.9; root.hub = 2;
    const subs = [], want = Math.max(2, Math.round(size / 45));
    for (let j = 0; j < want; j++){                // the sub-containers sit on a ring around the root, one per sector
      const ang = 6.283 * j / want, tx = c.cx + Math.cos(ang) * c.sp * .9, ty = c.cy + Math.sin(ang) * c.sp * .9;
      const sub = free.filter(n => !n.hub).reduce((x, y) => d2(y, tx, ty) < d2(x, tx, ty) ? y : x);
      sub.name = (k8s ? "ns-" : "subnet-") + (0x1000 + sub.i).toString(16); sub.type = k8s ? "container" : "network"; sub.r = 1.4; sub.hub = 1; subs.push(sub);
    }
    subs.forEach(s => edges.push([root.i, s.i, 4]));
    for (let i = lo; i < hi; i++){ const n = nodes[i]; if (n.hub) continue; const s = subs.reduce((a, b) => d2(n, b.x, b.y) < d2(n, a.x, a.y) ? b : a); edges.push([s.i, n.i, 4]); }
  });
  roots.slice(0, -1).forEach(r => edges.push([roots[roots.length - 1].i, r.i, 1]));      // each cluster's root is linked to the shared one
  /* Resources a complete scan no longer lists (the product marks them absent; it never deletes them). They stay on the
     map, drawn as gone, and are not counted among the resources being watched. Appended last, from their own random
     stream, so nothing above moves. `gone.h` = how many hours ago they were last seen. */
  let gs = 20261112;
  const Gr = () => { gs |= 0; gs = gs + 0x6D2B79F5 | 0; let t = Math.imul(gs ^ gs >>> 15, 1 | gs); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  [[0, "i-", "compute", 1.1], [0, "vol-", "storage", 1.1], [1, "elb-", "network", 6.5]].forEach(([ci, pre, type, h]) => {
    const c = C[ci], i = nodes.length, n = {i, x: c.cx + (Gr() - .5) * c.sp * 2.4, y: c.cy + (Gr() - .5) * c.sp * 2.4, cl: ci, r: .9, ph: Gr() * 6.28, b: i % 6,
      name: pre + (0x1000 + i).toString(16), type, account: c.account, region: c.region, gone: {h}};
    nodes.push(n);
    const sub = nodes.filter(m => m.hub === 1 && m.cl === ci).reduce((a, b) => (b.x - n.x) ** 2 + (b.y - n.y) ** 2 < (a.x - n.x) ** 2 + (a.y - n.y) ** 2 ? b : a);
    edges.push([sub.i, n.i, 4]);
  });
  /* depth, for a 3D view: its own random stream, so the flat layout above stays exactly as it was */
  let zs = 20261111;
  const Z = () => { zs |= 0; zs = zs + 0x6D2B79F5 | 0; let t = Math.imul(zs ^ zs >>> 15, 1 | zs); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  nodes.forEach(n => { const c = C[n.cl]; n.z = (c.cz || 0) + (Z() + Z() + Z() + Z() - 2) / 2 * c.sp * 1.5; });
  return {nodes, edges, hot};
};
/* who is linked to whom: adj[i] = [[j, flags, out], …] — out: 1 = the link runs from i to j, 0 = from j to i. Built once per map. */
const adjOf = sky => sky.adj || (sky.adj = (() => { const a = sky.nodes.map(() => []); sky.edges.forEach(([x, y, f]) => { a[x].push([y, f, 1]); a[y].push([x, f, 0]); }); return a; })());
const OPEN = ["critical", "warning", "notice"];

NF.world = {
  adj: adjOf,
  /* «only what is around it»: the resource and everything within `hops` links of it, as a Set of node indexes */
  around(sky, node, hops = 1){
    const adj = adjOf(sky), seen = new Set([node.i]); let edge = [node.i];
    for (let h = 0; h < hops; h++){ const next = []; edge.forEach(i => adj[i].forEach(([j]) => { if (!seen.has(j)){ seen.add(j); next.push(j); } })); edge = next; }
    return seen;
  },
  /* the shortest chain of links from a to b, as node indexes — null when there is none within maxHops (or a is b) */
  path(sky, a, b, maxHops = 8){
    if (!a || !b || a.i === b.i) return null;
    const adj = adjOf(sky), from = new Map([[a.i, -1]]); let edge = [a.i];
    for (let h = 0; h < maxHops && edge.length; h++){
      const next = [];
      for (const i of edge) for (const [j] of adj[i]){
        if (from.has(j)) continue; from.set(j, i);
        if (j === b.i){ const out = [j]; let k = i; while (k !== -1){ out.push(k); k = from.get(k); } return out.reverse(); }
        next.push(j);
      }
      edge = next;
    }
    return null;
  },
  /* Is this named resource «not normal» at that hour? Now: unless its item has been fixed, closed or cancelled. */
  active(h, hoursAgo, store){
    const it = store.get(h.ref);
    if (hoursAgo === 0 && it && CLOSED.includes(it.status)) return false;
    return hoursAgo <= h.from && hoursAgo >= h.to;
  },
  /* five answers: critical | warning | notice | unknown (no open issue — never «healthy») | gone (a complete scan no longer lists it) */
  health(node, hoursAgo, store){
    if (node.gone && hoursAgo <= node.gone.h) return "gone";
    const h = node.hot; return !h || !NF.world.active(h, hoursAgo, store) ? "unknown" : TONE[h.tone] || "notice";
  },
  present: sky => sky.nodes.filter(n => !n.gone),
  /* A link runs from its first end to its second — upstream to downstream, container to member — unless a model inferred it:
     an inferred relation has no known direction, and none is drawn. */
  dir: e => e[2] & 2 ? 0 : 1,
  relation: ([, f, out]) => f & 2 ? "inferred" : out ? "down" : "up",          // what the neighbour is to the resource whose list it is in
  totals(sky){
    const T = sky.totals; if (T) return T;
    const inferred = sky.edges.filter(e => e[2] & 2).length, gone = sky.nodes.filter(n => n.gone).length;
    return sky.totals = {nodes: sky.nodes.length, present: sky.nodes.length - gone, gone, links: sky.edges.length, inferred, rule: sky.edges.length - inferred,
      contain: sky.edges.filter(e => e[2] & 4).length, cross: sky.edges.filter(e => e[2] & 1).length};
  },
  abnormal: (sky, hoursAgo, store) => sky.hot.filter(h => NF.world.active(h, hoursAgo, store)),
  /* f = {account?, type?, onlyAbnormal?}; ctx = {hoursAgo, store} */
  match(node, f, ctx){
    if (f.account && node.account !== f.account) return false;
    if (f.type && node.type !== f.type) return false;
    if (f.onlyAbnormal && !OPEN.includes(NF.world.health(node, ctx.hoursAgo, ctx.store))) return false;
    return true;
  },
  /* By name, type or I# / C#. Resources with something open come first. */
  search(sky, q, ctx, limit = 8){
    q = (q || "").trim().toLowerCase(); if (!q) return [];
    const ref = q.replace("#", "").toUpperCase(), typeHit = NF.TYPES.filter(t => t.id.includes(q) || NF.t("type." + t.id).toLowerCase().includes(q)).map(t => t.id);
    const open = n => OPEN.includes(NF.world.health(n, ctx.hoursAgo, ctx.store)) ? 0 : 1;
    return sky.nodes.filter(n => n.name.toLowerCase().includes(q) || typeHit.includes(n.type) || (n.hot && n.hot.ref === ref))
      .sort((a, b) => open(a) - open(b) || (b.name.toLowerCase().startsWith(q) - a.name.toLowerCase().startsWith(q)) || a.i - b.i).slice(0, limit);
  },
  /* ── ONE result for both views ─────────────────────────────────────────────────────────────────────────────
     Everything the flat map and the 3D map show comes from here, and so do the numbers in the panels: neither view
     decides anything by itself. F = what the person asked for: {q, account, type, onlyAbnormal, sel, focus, a, b}.
     A path beats «only what is around it», which beats the filters. A search highlights; it never hides. */
  scene(sky, F, ctx){
    const W = NF.world, at = ctx.hoursAgo, store = ctx.store;
    const path = F.a && F.b ? W.path(sky, F.a, F.b) : null, pathSet = path ? new Set(path) : null;
    const around = !pathSet && F.focus && F.sel ? W.around(sky, F.sel, 1) : null;
    const filtered = !!(F.account || F.type || F.onlyAbnormal);
    let dim = null;
    if (pathSet || around || filtered){
      dim = new Set();
      sky.nodes.forEach(n => { if (!(pathSet ? pathSet.has(n.i) : around ? around.has(n.i) : W.match(n, F, ctx))) dim.add(n.i); });
    }
    const gone = new Set(); sky.nodes.forEach(n => { if (n.gone && at <= n.gone.h) gone.add(n.i); });
    const open = W.abnormal(sky, at, store);
    const rings = open.map(h => ({node: h.node, tone: h.tone, dim: !!dim && dim.has(h.node.i)}));      // every resource that is not normal wears a ring; outside the view, faintly
    const hits = W.search(sky, F.q, ctx), labels = new Map();
    rings.forEach(r => { if (!r.dim) labels.set(r.node.i, r.node); }); hits.forEach(n => labels.set(n.i, n)); (path || []).forEach(i => labels.set(i, sky.nodes[i]));
    [F.b, F.a, F.sel].forEach(n => { if (n){ labels.delete(n.i); labels.set(n.i, n); } });           // the ones being looked at come last, so their names end up on top
    let shown = 0; sky.nodes.forEach(n => { if (!gone.has(n.i) && !(dim && dim.has(n.i))) shown++; });
    /* How the map relates to the queue, so the two numbers can be told apart: of what waits on a person now, which items wear a
       ring, which sit on a resource that is back to normal (an acceptance, say), and which are on no resource of the map at all. */
    const onMap = new Set(sky.hot.map(h => h.ref)), ringRefs = new Set(open.map(h => h.ref)), waiting = at === 0 ? store.waiting() : [];
    return { dim, gone, shown, rings, hits, path, pathSet, around, labels: [...labels.values()], totals: W.totals(sky), at,
      abnormal: open.filter(h => W.match(h.node, F, ctx)),                                              // what the panel lists: the filters apply, a focus or a path does not
      ringed: waiting.filter(i => ringRefs.has(i.id)), quiet: waiting.filter(i => onMap.has(i.id) && !ringRefs.has(i.id)), offMap: waiting.filter(i => !onMap.has(i.id)) };
  },
  /* What a view must have on its canvas for this result. The flat map shows containment as the cluster itself, so it draws
     no containment lines; the 3D map draws every link. */
  expected(sc, view){
    const T = sc.totals;
    return { nodes: T.nodes, bright: sc.shown, gone: sc.gone.size, rings: sc.rings.length, ringsBright: sc.rings.filter(r => !r.dim).length,
             links: view === "2d" ? T.links - T.contain : T.links, named: sc.labels.length };
  },
  /* The check: what the view says it drew against what the data says. [] = they agree. */
  reconcile(sc, view, drawn){
    const want = NF.world.expected(sc, view);
    return Object.keys(want).filter(k => drawn[k] !== want[k]).map(k => ({what: k, want: want[k], got: drawn[k]}));
  },
  /* The next event further back (dir -1) or closer to now (dir +1); past the latest one is «now» (0). */
  stepEvent(events, hoursAgo, dir){
    const hs = events.map(e => e.h);
    if (dir < 0){ const older = hs.filter(h => h > hoursAgo + 1e-9); return older.length ? Math.min(...older) : hoursAgo; }
    const newer = hs.filter(h => h < hoursAgo - 1e-9); return newer.length ? Math.max(...newer) : 0;
  },
};
})();
