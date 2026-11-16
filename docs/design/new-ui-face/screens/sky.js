/* new-UI-face — the flat star map behind every lens: every resource is a star, the ones with something open wear a ring.
   The layout comes from NF.buildSky and WHAT to show from NF.world.scene (model-world.js): this file decides nothing, it
   draws the result it is handed and reports what it drew (NF.sky.stats), so the lens can check one against the other.
   Drawing is batched (a handful of paths per frame, not one per star); NF.sky.fps / drawMs say how it is doing. */
(function(){
"use strict";
const NF = window.NF, S = NF.S;
const LBL = "12px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif";
let cv, cx, W = 0, H = 0, DPR = 1, colors = {};
const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const cam = {x: 0, y: 0, z: 1, tx: 0, ty: 0, tz: 1};
let sky = {nodes: [], edges: [], hot: []}, adj = [];
/* what the world lens asked for: sc = the shared result, sel = the selected resource; free = the person moved the camera;
   blank = loading / failed / no resources; off = the 3D view is showing instead */
const view = {sc: null, sel: null, free: false, blank: false, off: false};
let frames = 0, fpsAt = 0, drawn = {nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0};

function rebuild(count){
  sky = NF.buildSky(NF.seed, count ? {count} : {});
  adj = NF.world.adj(sky);
  view.sc = null; view.sel = null; view.free = false;
  NF.sky.nodes = sky.nodes; NF.sky.edges = sky.edges; NF.sky.hot = sky.hot; NF.sky.data = sky;
}
function recolor(){
  const cs = getComputedStyle(document.body), g = n => cs.getPropertyValue(n).trim();
  colors = {ink2: g("--ink2"), star: g("--star"), amber: g("--amber"), mint: g("--mint"), red: g("--red"), violet: g("--violet"), dim: g("--dim"), chalk: g("--chalk")};
}
function resize(){ DPR = Math.min(2, window.devicePixelRatio || 1); W = cv.clientWidth; H = cv.clientHeight; cv.width = W * DPR; cv.height = H * DPR; aim(); }

function focusHot(){ if (S.lens !== "decide") return null; const it = NF.current(); return it ? sky.hot.find(h => h.ref === it.id) || null : null; }
const scale = z => Math.min(W, H) * .5 * z;

/* Where the camera should be. In the world lens a person may have moved it (view.free) or picked a node to fly to. */
function aim(){
  if (!cv) return;
  if (S.lens === "world"){
    if (view.free) return;
    const narrow = W <= 760; cam.tx = 0; cam.ty = narrow ? -.42 : .05; cam.tz = narrow ? .86 : .92; return;
  }
  view.free = false;
  const h = focusHot();
  if (h){                                           // the focused resource lands in the gap right of the brief
    cam.tz = 1.3; const sc = scale(cam.tz), wide = W > 1180, px = wide ? W / 2 + 494 : W / 2, py = wide ? H * .68 : H / 2;
    cam.tx = h.node.x - (px - W / 2) / sc; cam.ty = h.node.y - (py - H / 2) / sc;
  } else { cam.tx = 0; cam.ty = 0; cam.tz = 1.05; }
}
function flyTo(n, z = 2.6){ view.free = true; cam.tz = Math.max(cam.tz, z); cam.tx = n.x; cam.ty = n.y; }
function home(){ view.free = false; aim(); }
function zoomAt(px, py, factor){                    // zoom around a point on screen (the wheel)
  const sc0 = scale(cam.tz), wx = cam.tx + (px - W / 2) / sc0, wy = cam.ty + (py - H / 2) / sc0;
  cam.tz = Math.max(.6, Math.min(8, cam.tz * factor)); const sc1 = scale(cam.tz);
  cam.tx = wx - (px - W / 2) / sc1; cam.ty = wy - (py - H / 2) / sc1; view.free = true;
}
function panBy(dx, dy){ const sc = scale(cam.z); cam.tx -= dx / sc; cam.ty -= dy / sc; cam.x = cam.tx; cam.y = cam.ty; view.free = true; }

function draw(ts){
  const t = ts / 1000, t0 = performance.now();
  frames++; if (ts - fpsAt >= 1000){ NF.sky.fps = Math.round(frames * 1000 / (ts - fpsAt)); frames = 0; fpsAt = ts; }
  cam.x += (cam.tx - cam.x) * .08; cam.y += (cam.ty - cam.y) * .08; cam.z += (cam.tz - cam.z) * .08;
  const sc = scale(cam.z), ox = W / 2, oy = H / 2, world = S.lens === "world", f = focusHot(), N = sky.nodes;
  cx.setTransform(DPR, 0, 0, DPR, 0, 0); cx.clearRect(0, 0, W, H);
  if (world && (view.blank || view.off)){ requestAnimationFrame(draw); return; }           // loading / failed / no resources, or the 3D view is on: an empty sky says so
  /* outside the world lens the map is the backdrop: everything as it is now, nothing dimmed */
  const R = world && view.sc ? view.sc : backdrop(), faint = R.dim, gone = R.gone, D = {nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0};
  for (let i = 0; i < N.length; i++){ const n = N[i]; n.sx = ox + (n.x - cam.x) * sc; n.sy = oy + (n.y - cam.y) * sc; n.on = n.sx > -20 && n.sx < W + 20 && n.sy > -20 && n.sy < H + 20; }

  /* links: four paths — ordinary, between clusters, model-inferred (dashed), and those outside what is being looked at */
  const P = [new Path2D(), new Path2D(), new Path2D(), new Path2D()], E = sky.edges;
  for (let k = 0; k < E.length; k++){
    const e = E[k]; if (e[2] & 4) continue;                                      // containment is the cluster itself; its line shows for the selected resource only
    D.links++;
    const A = N[e[0]], B = N[e[1]]; if (!A.on && !B.on) continue;
    const p = faint && (faint.has(e[0]) || faint.has(e[1])) ? P[3] : e[2] & 2 ? P[2] : e[2] & 1 ? P[1] : P[0];
    p.moveTo(A.sx, A.sy); p.lineTo(B.sx, B.sy);
  }
  cx.lineWidth = 1;
  cx.strokeStyle = `rgba(${colors.star},${world ? .13 : .055})`; cx.stroke(P[0]);
  cx.strokeStyle = `rgba(${colors.star},${world ? .07 : .035})`; cx.stroke(P[1]);
  if (world){ cx.setLineDash([3, 4]); cx.strokeStyle = `rgba(${colors.star},.22)`; cx.stroke(P[2]); cx.setLineDash([]); cx.strokeStyle = `rgba(${colors.star},.03)`; cx.stroke(P[3]); }
  else { cx.strokeStyle = `rgba(${colors.star},.055)`; cx.stroke(P[2]); }

  /* stars: six twinkle groups, each one path; outside the view in one faint path; the ones that are gone as hollow rings */
  const grow = world ? 1.25 * Math.min(2.2, Math.max(1, cam.z * .7)) : 1, B6 = [new Path2D(), new Path2D(), new Path2D(), new Path2D(), new Path2D(), new Path2D()], F = new Path2D(), G = new Path2D(), G2 = new Path2D();
  for (let i = 0; i < N.length; i++){
    const n = N[i], isGone = gone.has(i), off = faint && faint.has(i);
    D.nodes++; if (isGone) D.gone++; else if (!off) D.bright++;
    if (!n.on) continue;
    const r = n.r * grow;
    if (isGone){ const g = off ? G2 : G; g.moveTo(n.sx + 3.2, n.sy); g.arc(n.sx, n.sy, 3.2, 0, 6.283); continue; }       // gone stays «gone» even outside the view, only fainter
    const p = off ? F : B6[n.b]; p.moveTo(n.sx + r, n.sy); p.arc(n.sx, n.sy, r, 0, 6.283);
  }
  for (let b = 0; b < 6; b++){ const tw = reduce ? .75 : .55 + .35 * Math.sin(t * 1.3 + b * 1.047); cx.fillStyle = `rgba(${colors.star},${(world ? .78 : .34) * tw})`; cx.fill(B6[b]); }
  if (faint){ cx.fillStyle = `rgba(${colors.star},.1)`; cx.fill(F); }
  cx.setLineDash([2, 2]); cx.lineWidth = 1; cx.strokeStyle = `rgba(${colors.star},${world ? .7 : .3})`; cx.stroke(G); cx.strokeStyle = `rgba(${colors.star},.2)`; cx.stroke(G2); cx.setLineDash([]);

  /* the links of the focused (decide) or the selected (world) resource; a dot runs along each one from upstream to downstream */
  const lit = world ? view.sel : f && f.node, tone = world ? colors.chalk : f && colors[f.tone];
  if (lit && !(world && R.pathSet)){
    cx.strokeStyle = tone; cx.globalAlpha = .75; cx.lineWidth = 1.2;
    adj[lit.i].forEach(([j, fl]) => { const m = N[j]; cx.setLineDash(fl & 2 ? [3, 4] : []); cx.beginPath(); cx.moveTo(lit.sx, lit.sy); cx.lineTo(m.sx, m.sy); cx.stroke(); });
    cx.setLineDash([]); cx.globalAlpha = 1;
    if (world){
      cx.fillStyle = colors.chalk; adj[lit.i].forEach(([j]) => { const m = N[j]; cx.beginPath(); cx.arc(m.sx, m.sy, 2.4, 0, 6.283); cx.fill(); });
      if (!reduce) adj[lit.i].forEach(([j, fl, out], k) => {                   // an inferred relation has no known direction: no dot
        if (fl & 2) return; const m = N[j], from = out ? lit : m, to = out ? m : lit, u = (t * .45 + k * .37) % 1;
        cx.fillStyle = colors.mint; cx.beginPath(); cx.arc(from.sx + (to.sx - from.sx) * u, from.sy + (to.sy - from.sy) * u, 2.2, 0, 6.283); cx.fill();
      });
    }
  }
  /* a path between two resources: how they are linked — not a claim that a fault travels along it */
  if (world && R.path){
    cx.strokeStyle = colors.mint; cx.lineWidth = 2.2; cx.beginPath();
    R.path.forEach((i, k) => { const n = N[i]; if (k) cx.lineTo(n.sx, n.sy); else cx.moveTo(n.sx, n.sy); }); cx.stroke();
    R.path.forEach(i => { const n = N[i]; cx.fillStyle = colors.chalk; cx.beginPath(); cx.arc(n.sx, n.sy, 3, 0, 6.283); cx.fill(); });
  }
  /* resources with something open */
  R.rings.forEach(r => {
    const n = r.node, c = colors[r.tone], isF = f && f.node === n, pul = reduce ? 1 : 1 + .35 * Math.sin(t * 2.4 + n.ph);
    D.rings++; if (!r.dim) D.ringsBright++;
    cx.strokeStyle = c; cx.globalAlpha = r.dim ? .18 : isF ? .9 : .5; cx.lineWidth = isF ? 2 : 1.2; cx.beginPath(); cx.arc(n.sx, n.sy, (isF ? 13 : 8) * pul, 0, 6.283); cx.stroke();
    cx.globalAlpha = r.dim ? .25 : 1; cx.fillStyle = c; cx.beginPath(); cx.arc(n.sx, n.sy, isF ? 4.5 : 3.4, 0, 6.283); cx.fill(); cx.globalAlpha = 1;
    if (isF) label(n, n.name);
  });
  if (world){
    R.hits.forEach(n => { cx.strokeStyle = colors.chalk; cx.lineWidth = 1.4; cx.beginPath(); cx.arc(n.sx, n.sy, 7, 0, 6.283); cx.stroke(); });
    if (view.sel){ const n = view.sel; cx.strokeStyle = colors.chalk; cx.lineWidth = 2; cx.beginPath(); cx.arc(n.sx, n.sy, 11, 0, 6.283); cx.stroke(); }
    R.labels.forEach(n => { D.named++; label(n, n.name, gone.has(n.i)); });
    if (cam.z < 2 && !R.pathSet){ cx.font = LBL; cx.fillStyle = colors.dim; cx.globalAlpha = .85; cx.textAlign = "center";
      NF.seed.clusters.forEach(c => { cx.fillText(NF.tx(c.name), ox + (c.cx - cam.x) * sc, oy + (c.cy - c.sp * 1.62 - cam.y) * sc); }); cx.textAlign = "start"; cx.globalAlpha = 1; }
  } else D.named = R.labels.length;
  drawn = D;
  NF.sky.drawMs += (performance.now() - t0 - NF.sky.drawMs) * .05;         // what one frame costs, smoothed — the screen's refresh rate caps fps, not this
  requestAnimationFrame(draw);
}
function label(n, text, struck){
  cx.font = LBL; const w = cx.measureText(text).width; cx.globalAlpha = .78; cx.fillStyle = colors.ink2; cx.fillRect(n.sx + 12, n.sy - 9, w + 10, 18);
  cx.globalAlpha = 1; cx.fillStyle = struck ? colors.dim : colors.chalk; cx.fillText(text, n.sx + 17, n.sy + 4);
  if (struck){ cx.strokeStyle = colors.dim; cx.lineWidth = 1; cx.beginPath(); cx.moveTo(n.sx + 16, n.sy); cx.lineTo(n.sx + 18 + w, n.sy); cx.stroke(); }
}
/* the same result the world lens would get with nothing asked for, as of now — worked out again twice a second at most */
let back = null, backAt = 0;
function backdrop(){
  const now = performance.now();
  if (!back || now - backAt > 500 || back.sky !== sky){ back = NF.world.scene(sky, {}, {hoursAgo: 0, store: NF.store}); back.sky = sky; backAt = now; }
  return back;
}

NF.sky = {
  nodes: [], edges: [], hot: [], data: sky, fps: 0, drawMs: 0, view, aim, recolor, rebuild, flyTo, home, zoomAt, panBy,
  /* hand over what to show (the shared result) and which resource is selected */
  apply(sc, sel){ view.sc = sc; view.sel = sel || null; },
  stats: () => drawn,                               // what the last frame put on the canvas, counted while drawing
  init(canvas){ cv = canvas; cx = cv.getContext("2d"); rebuild(); recolor(); resize(); window.addEventListener("resize", resize); requestAnimationFrame(draw); },
  /* the resource nearest to a point on screen, within 18 px; rings win over plain stars */
  pick(x, y){
    let best = null, bd = 18 * 18;
    sky.nodes.forEach(n => { if (!n.on) return; let d = (n.sx - x) ** 2 + (n.sy - y) ** 2; if (n.hot) d *= .35; if (d < bd){ bd = d; best = n; } });
    return best;
  },
};
})();
