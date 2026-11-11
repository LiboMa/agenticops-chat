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
   (flags: 1 = between clusters, 2 = inferred by a model — advisory, drawn dashed). opts.count scales every cluster. */
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
  return {nodes, edges, hot};
};

NF.world = {
  /* Is this named resource «not normal» at that hour? Now: unless its item has been fixed, closed or cancelled. */
  active(h, hoursAgo, store){
    const it = store.get(h.ref);
    if (hoursAgo === 0 && it && CLOSED.includes(it.status)) return false;
    return hoursAgo <= h.from && hoursAgo >= h.to;
  },
  health(node, hoursAgo, store){ const h = node.hot; return !h || !NF.world.active(h, hoursAgo, store) ? "unknown" : TONE[h.tone] || "notice"; },
  abnormal: (sky, hoursAgo, store) => sky.hot.filter(h => NF.world.active(h, hoursAgo, store)),
  /* f = {account?, type?, onlyAbnormal?}; ctx = {hoursAgo, store} */
  match(node, f, ctx){
    if (f.account && node.account !== f.account) return false;
    if (f.type && node.type !== f.type) return false;
    if (f.onlyAbnormal && NF.world.health(node, ctx.hoursAgo, ctx.store) === "unknown") return false;
    return true;
  },
  /* By name, type or I# / C#. Resources with something open come first. */
  search(sky, q, ctx, limit = 8){
    q = (q || "").trim().toLowerCase(); if (!q) return [];
    const ref = q.replace("#", "").toUpperCase(), typeHit = NF.TYPES.filter(t => t.id.includes(q) || NF.t("type." + t.id).toLowerCase().includes(q)).map(t => t.id);
    const open = n => NF.world.health(n, ctx.hoursAgo, ctx.store) !== "unknown" ? 0 : 1;
    return sky.nodes.filter(n => n.name.toLowerCase().includes(q) || typeHit.includes(n.type) || (n.hot && n.hot.ref === ref))
      .sort((a, b) => open(a) - open(b) || (b.name.toLowerCase().startsWith(q) - a.name.toLowerCase().startsWith(q)) || a.i - b.i).slice(0, limit);
  },
  /* The next event further back (dir -1) or closer to now (dir +1); past the latest one is «now» (0). */
  stepEvent(events, hoursAgo, dir){
    const hs = events.map(e => e.h);
    if (dir < 0){ const older = hs.filter(h => h > hoursAgo + 1e-9); return older.length ? Math.min(...older) : hoursAgo; }
    const newer = hs.filter(h => h < hoursAgo - 1e-9); return newer.length ? Math.max(...newer) : 0;
  },
};
})();
