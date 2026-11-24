/* new-UI-face — the 3D view of the «全景» lens. Like sky.js it decides nothing: it draws the result NF.world.scene hands it
   and reports what is on its canvas (NF.sky3.stats, read back from the engine's own objects), so the lens can check it.
   The engine (3d-force-graph, vendor/) is loaded the first time someone switches to 3D — the rest of the prototype
   never needs it. Names and rings are page elements laid over the canvas: only a dozen resources need one. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), W = NF.world;
const SC = 430, reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
/* how a resource is drawn, by opacity — the check reads these back from the engine's materials */
const A = {dim: .05, goneDim: .12, gone: .22, plain: .6, hub: .95, ring: 1};
let G = null, V3 = null, col = {}, sky = null, data = null, sc = null, sel = null, marks = [], cb = {}, raf = 0, frames = 0, fpsAt = 0;

const pos = n => ({x: n.x * SC, y: -n.y * SC, z: n.z * SC});
const ringOf = n => sc.rings.find(r => r.node === n);
const isDim = n => !!sc.dim && sc.dim.has(n.i);
const alpha = n => sc.gone.has(n.i) ? (isDim(n) ? A.goneDim : A.gone) : isDim(n) ? A.dim : ringOf(n) ? A.ring : n.hub ? A.hub : A.plain;   // gone stays «gone» even outside the view
const onPath = l => !!sc.path && sc.path.some((i, k) => k && ((sc.path[k - 1] === l.a && i === l.b) || (sc.path[k - 1] === l.b && i === l.a)));
const ofSel = l => !!sel && !sc.pathSet && (l.a === sel.i || l.b === sel.i);

function recolor(){
  const cs = getComputedStyle(document.body), g = k => cs.getPropertyValue(k).trim();
  col = {star: g("--star"), amber: g("--amber"), mint: g("--mint"), red: g("--red"), violet: g("--violet"), chalk: g("--chalk")};
}
function build(){
  sky = NF.sky.data;
  data = { nodes: sky.nodes.map(n => { const p = pos(n); return {id: n.i, n, x: p.x, y: p.y, z: p.z, fx: p.x, fy: p.y, fz: p.z}; }),
           links: sky.edges.map(([a, b, f]) => ({source: a, target: b, f, a, b})) };
  if (G) G.graphData(data);
}
function style(){
  if (!G || !sc) return;
  G.nodeColor(d => { const n = d.n, r = ringOf(n), a = alpha(n); return r && !r.dim ? col[r.tone] : `rgba(${col.star},${a})`; })
   .nodeVal(d => ringOf(d.n) ? 16 : d.n.hub === 2 ? 12 : d.n.hub ? 5 : 1.4)
   .linkColor(l => onPath(l) ? col.mint : ofSel(l) ? col.chalk : isDim(sky.nodes[l.a]) || isDim(sky.nodes[l.b]) ? `rgba(${col.star},.03)` : `rgba(${col.star},${l.f & 4 ? .1 : l.f & 2 ? .5 : l.f & 1 ? .4 : .28})`)
   .linkWidth(l => onPath(l) ? 2.2 : ofSel(l) ? 1 : 0)
   .linkCurvature(l => l.f & 2 ? .32 : 0)                                    // a relation a model inferred is drawn as a curve (the flat map dashes it)
   .linkDirectionalParticles(l => ofSel(l) && W.dir([l.a, l.b, l.f]) ? 2 : 0);    // upstream → downstream, on the selected resource's links only; none where the direction is unknown
  marks = sc.rings.map(r => ({n: r.node, tone: r.tone, off: r.dim, ring: true}));
  sc.labels.forEach(n => { if (!marks.some(m => m.n === n)) marks.push({n, off: false}); });
  marks.forEach(m => { m.sel = m.n === sel; m.named = sc.labels.includes(m.n); m.gone = sc.gone.has(m.n.i); });
  marks.sort((x, y) => sc.labels.indexOf(x.n) - sc.labels.indexOf(y.n));     // the ones being looked at come last, on top
}
function frame(ts){
  raf = requestAnimationFrame(frame);
  frames++; if (ts - fpsAt >= 1000){ NF.sky3.fps = Math.round(frames * 1000 / (ts - fpsAt)); frames = 0; fpsAt = ts; }
  if (!sc) return;
  const cam = G.camera(), cbox = $("#clabels"), far = !(sc.pathSet || sel);
  NF.seed.clusters.forEach((c, k) => {                      // the cluster names float above each cluster, in the overview only
    let el = cbox.children[k]; if (!el){ cbox.insertAdjacentHTML("beforeend", `<div class="c3"></div>`); el = cbox.children[k]; }
    const v = new V3(c.cx * SC, -(c.cy - c.sp * 1.75) * SC, (c.cz || 0) * SC).project(cam);
    el.hidden = v.z > 1 || !far; if (el.hidden) return;
    el.style.transform = `translate(${(v.x + 1) / 2 * innerWidth}px,${(1 - v.y) / 2 * innerHeight}px) translate(-50%,-50%)`; const name = tx(c.name); if (el.textContent !== name) el.textContent = name;
  });
  const box = $("#labels"), have = box.children;
  while (have.length < marks.length) box.insertAdjacentHTML("beforeend", `<div class="l3"><i></i><span></span></div>`);
  for (let k = 0; k < have.length; k++){
    const el = have[k], m = marks[k]; if (!m){ el.hidden = true; el.dataset.i = el.dataset.ring = el.dataset.named = ""; continue; }   // a leftover from an earlier result must not count
    const p = pos(m.n), v = new V3(p.x, p.y, p.z).project(cam);
    el.dataset.i = m.n.i; el.dataset.ring = m.ring ? (m.off ? "faint" : "bright") : ""; el.dataset.named = m.named ? "1" : "";
    if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1){ el.hidden = true; continue; }
    el.hidden = false; el.style.transform = `translate(${(v.x + 1) / 2 * innerWidth}px,${(1 - v.y) / 2 * innerHeight}px)`;
    el.className = "l3" + (m.ring ? " t-" + m.tone : "") + (m.sel ? " sel" : "") + (m.off ? " off" : "") + (m.gone ? " gone" : "") + (m.named ? "" : " mute");
    if (el.lastChild.textContent !== m.n.name) el.lastChild.textContent = m.n.name;
  }
}
function init(){
  recolor();
  const el = $("#g3d");
  try { G = new ForceGraph3D(el, {controlType: "orbit"}); } catch (e){ G = ForceGraph3D({controlType: "orbit"})(el); }
  G.backgroundColor("rgba(0,0,0,0)").showNavInfo(false).enableNodeDrag(false).nodeRelSize(2.1).nodeResolution(6).nodeOpacity(1).nodeLabel(() => "")
   .linkOpacity(1).linkDirectionalParticleSpeed(.006).linkDirectionalParticleWidth(2.4).linkDirectionalParticleColor(() => col.mint)
   .cooldownTicks(0).warmupTicks(0)
   .onNodeClick(d => cb.pick && cb.pick(d.n)).onBackgroundClick(() => cb.pick && cb.pick(null))
   .onNodeHover(d => { el.style.cursor = d ? "pointer" : "grab"; if (cb.hover) cb.hover(d ? d.n : null); });
  el.addEventListener("pointermove", e => { if (cb.move) cb.move(e); });
  el.addEventListener("pointerdown", () => { if (NF.sky3.turning){ NF.sky3.turn(false); if (cb.changed) cb.changed(); } });   // taking the map in hand stops the turning
  window.addEventListener("resize", () => G.width(innerWidth).height(innerHeight));
  V3 = G.camera().position.constructor;
  build(); home(0); NF.sky3.turn(!reduce); NF.sky3.ready = true;
}
function home(ms = 900){ if (G) G.cameraPosition({x: 0, y: -140, z: innerWidth < 760 ? 1500 : 1050}, {x: 0, y: 0, z: 0}, ms); }

NF.sky3 = {
  ready: false, failed: false, fps: 0, turning: false,
  /* fetch the engine once; done(ok) */
  load(done){
    if (NF.sky3.ready) return done(true);
    const s = document.createElement("script"); s.src = "vendor/3d-force-graph.min.js";
    s.onload = () => { try { init(); done(true); } catch (e){ NF.sky3.failed = true; done(false); } };
    s.onerror = () => { NF.sky3.failed = true; done(false); };
    document.head.appendChild(s);
  },
  on(handlers){ cb = handlers; },
  show(on){
    ["#g3d", "#labels", "#clabels"].forEach(q => { $(q).hidden = !on; });
    if (!G) return;
    if (on){ G.width(innerWidth).height(innerHeight).resumeAnimation(); if (!raf) raf = requestAnimationFrame(frame); }
    else { G.pauseAnimation(); cancelAnimationFrame(raf); raf = 0; }
  },
  /* hand over what to show (the shared result) and which resource is selected */
  apply(scene, selected){ if (!G) return; if (sky !== NF.sky.data) build(); sc = scene; sel = selected || null; style(); },
  flyTo(n, ms = 1000){ const p = pos(n), r = Math.hypot(p.x, p.y, p.z) || 1, k = 1 + 400 / r; G.cameraPosition({x: p.x * k, y: p.y * k, z: p.z * k + (r < 80 ? 400 : 0)}, p, ms); },
  home, recolor(){ recolor(); style(); },
  turn(on){ NF.sky3.turning = on; if (G){ const c = G.controls(); c.autoRotate = on; c.autoRotateSpeed = .45; } },
  /* What is on the 3D canvas, read back from the engine's own objects (not from the result it was handed):
     how many spheres, how many of them at full strength, how many drawn as gone, how many lines, how many rings and names. */
  stats(){
    const out = {nodes: 0, bright: 0, gone: 0, rings: 0, ringsBright: 0, links: 0, named: 0};
    if (!G) return out;
    G.graphData().nodes.forEach(d => { const o = d.__threeObj, m = o && o.material; if (!m) return; out.nodes++;
      const a = m.opacity; if (a > .09 && a < .26) out.gone++; else if (a > .3) out.bright++; });
    G.graphData().links.forEach(l => { if (l.__lineObj) out.links++; });
    [...$("#labels").children].forEach(el => { if (!el.dataset.i) return; if (el.dataset.ring) out.rings++; if (el.dataset.ring === "bright") out.ringsBright++; if (el.dataset.named) out.named++; });
    return out;
  },
};
})();
