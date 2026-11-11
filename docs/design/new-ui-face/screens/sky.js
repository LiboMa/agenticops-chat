/* new-UI-face — the starfield behind every lens: resources as stars, the ones with something open as rings.
   A schematic layout from seeded random numbers, not a real topology. */
(function(){
"use strict";
const NF = window.NF, S = NF.S;
const LBL = "12px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif";
let cv, cx, W = 0, H = 0, DPR = 1, colors = {};
const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const cam = {x: 0, y: 0, z: 1, tx: 0, ty: 0, tz: 1};
const nodes = [], edges = [], hot = [];

function build(){
  let seed = 20261110;
  const R = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const gauss = () => (R() + R() + R() + R() - 2) / 2;
  const C = NF.seed.clusters;
  C.forEach((c, ci) => { for (let i = 0; i < c.n; i++) nodes.push({x: c.cx + gauss() * c.sp * 1.5, y: c.cy + gauss() * c.sp * 1.5, cl: ci, r: .55 + R() * 1.05, ph: R() * 6.28, name: null}); });
  NF.seed.hot.forEach(h0 => {                      // named resources keep apart inside their cluster
    const h = {...h0}, c = C[h.cl];
    const pool = nodes.filter(n => n.cl === h.cl && !n.name && Math.hypot(n.x - c.cx, n.y - c.cy) < c.sp * 1.5), named = nodes.filter(n => n.cl === h.cl && n.name);
    const score = n => named.length ? Math.min(...named.map(m => Math.hypot(n.x - m.x, (n.y - m.y) * 2.2))) : -Math.hypot(n.x - (c.cx - c.sp * .5), n.y - (c.cy - c.sp * .6));
    const n = pool.reduce((a, b) => score(b) > score(a) ? b : a);
    n.name = h.name; n.r = 2.4; h.node = n; hot.push(h);
  });
  nodes.forEach((a, i) => {
    nodes.map((b, j) => ({j, d: (a.x - b.x) ** 2 + (a.y - b.y) ** 2, same: b.cl === a.cl})).filter(o => o.j !== i && o.same)
         .sort((p, q) => p.d - q.d).slice(0, 2).forEach(o => { if (o.j > i) edges.push([i, o.j]); });
  });
  for (let k = 0; k < 10; k++){ const a = nodes.findIndex(n => n.cl === 4 && R() < .3), b = Math.floor(R() * nodes.length); if (a >= 0 && nodes[b].cl !== 4) edges.push([a, b, 1]); }
}
function recolor(){
  const cs = getComputedStyle(document.body), g = n => cs.getPropertyValue(n).trim();
  colors = {ink2: g("--ink2"), star: g("--star"), amber: g("--amber"), mint: g("--mint"), red: g("--red"), violet: g("--violet"), dim: g("--dim"), chalk: g("--chalk")};
}
function resize(){ DPR = Math.min(2, window.devicePixelRatio || 1); W = cv.clientWidth; H = cv.clientHeight; cv.width = W * DPR; cv.height = H * DPR; aim(); }

/* Is this resource "not normal" at the moment the world lens shows? Now: unless its item was fixed or closed. */
function active(h){
  const it = NF.store.get(h.ref);
  if (S.hoursAgo === 0 && it && (it.status === "fixed" || it.status === "done")) return false;
  return S.hoursAgo <= h.from && S.hoursAgo >= h.to;
}
function focusHot(){ if (S.lens !== "decide") return null; const it = NF.current(); return it ? hot.find(h => h.ref === it.id) || null : null; }

function aim(){
  if (!cv) return;
  if (S.lens === "world"){ const narrow = W <= 760; cam.tx = 0; cam.ty = narrow ? -.42 : .05; cam.tz = narrow ? .86 : .92; return; }
  const h = focusHot();
  if (h){                                           // the focused resource lands in the gap right of the brief
    cam.tz = 1.3; const sc = Math.min(W, H) * .5 * cam.tz, wide = W > 1180, px = wide ? W / 2 + 494 : W / 2, py = wide ? H * .68 : H / 2;
    cam.tx = h.node.x - (px - W / 2) / sc; cam.ty = h.node.y - (py - H / 2) / sc;
  } else { cam.tx = 0; cam.ty = 0; cam.tz = 1.05; }
}
function draw(ts){
  const t = ts / 1000;
  cam.x += (cam.tx - cam.x) * .06; cam.y += (cam.ty - cam.y) * .06; cam.z += (cam.tz - cam.z) * .06;
  const sc = Math.min(W, H) * .5 * cam.z, ox = W / 2, oy = H / 2, world = S.lens === "world", f = focusHot();
  cx.setTransform(DPR, 0, 0, DPR, 0, 0); cx.clearRect(0, 0, W, H);
  nodes.forEach(n => { n.sx = ox + (n.x - cam.x) * sc; n.sy = oy + (n.y - cam.y) * sc; });
  cx.lineWidth = 1;
  edges.forEach(([a, b, far]) => {
    const A = nodes[a], B = nodes[b], near = f && (A === f.node || B === f.node);
    cx.strokeStyle = near ? colors[f.tone] : `rgba(${colors.star},${far ? (world ? .07 : .04) : (world ? .14 : .07)})`; cx.globalAlpha = near ? .8 : 1;
    cx.beginPath(); cx.moveTo(A.sx, A.sy); cx.lineTo(B.sx, B.sy); cx.stroke();
  });
  cx.globalAlpha = 1;
  nodes.forEach(n => { const tw = reduce ? .75 : .55 + .35 * Math.sin(t * 1.3 + n.ph);
    cx.fillStyle = `rgba(${colors.star},${(world ? .75 : .42) * tw})`; cx.beginPath(); cx.arc(n.sx, n.sy, n.r * (world ? 1.25 : 1), 0, 6.283); cx.fill(); });
  hot.forEach(h => {
    if (!active(h)) return;
    const n = h.node, c = colors[h.tone], isF = f === h, pul = reduce ? 1 : 1 + .35 * Math.sin(t * 2.4 + n.ph);
    cx.strokeStyle = c; cx.globalAlpha = isF ? .9 : .5; cx.lineWidth = isF ? 2 : 1.2; cx.beginPath(); cx.arc(n.sx, n.sy, (isF ? 13 : 8) * pul, 0, 6.283); cx.stroke();
    cx.globalAlpha = 1; cx.fillStyle = c; cx.beginPath(); cx.arc(n.sx, n.sy, isF ? 4.5 : 3.4, 0, 6.283); cx.fill();
    if (world || isF){ cx.font = LBL; const w = cx.measureText(h.name).width; cx.globalAlpha = .78; cx.fillStyle = colors.ink2; cx.fillRect(n.sx + 12, n.sy - 9, w + 10, 18);
      cx.globalAlpha = 1; cx.fillStyle = colors.chalk; cx.fillText(h.name, n.sx + 17, n.sy + 4); }
  });
  if (world){ cx.font = LBL; cx.fillStyle = colors.dim; cx.globalAlpha = .85; cx.textAlign = "center";
    NF.seed.clusters.forEach(c => { cx.fillText(NF.tx(c.name), ox + (c.cx - cam.x) * sc, oy + (c.cy - c.sp * 1.62 - cam.y) * sc); }); cx.textAlign = "start"; cx.globalAlpha = 1; }
  requestAnimationFrame(draw);
}
NF.sky = {
  nodes, hot, active, aim, recolor,
  init(canvas){ cv = canvas; cx = cv.getContext("2d"); build(); recolor(); resize(); window.addEventListener("resize", resize); requestAnimationFrame(draw); },
  pick(x, y){ let best = null, bd = 18 * 18; nodes.forEach(n => { const d = (n.sx - x) ** 2 + (n.sy - y) ** 2; if (d < bd){ bd = d; best = n; } }); return best; },
};
})();
