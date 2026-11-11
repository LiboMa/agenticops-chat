/* new-UI-face — a 3D preview of the «全景» lens. Not part of the prototype proper: it exists to answer one question —
   what would we gain by borrowing from knowledge-graph-3d.tsx (the 3D knowledge graph of another project)?
   It uses the same engine that component uses (3d-force-graph, vendored under vendor/), our sample data, our rules
   (model-world.js) and our colours. Borrowed here: depth, fly-to, «only what is around it», a path between two
   resources, and particles that show which way a link runs. Not borrowed: one mesh group and one text texture per
   node — at 1,623 resources that is the difference between smooth and not (the «原组件的画法» switch shows it). */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, W = NF.world;
const SC = 430, reduce = matchMedia("(prefers-reduced-motion: reduce)").matches, q = new URLSearchParams(location.search);
const sky = NF.buildSky(NF.seed), store = NF.createStore(NF.seed, NF.realClock), ctx = {hoursAgo: 0, store};
const P = {sel: null, focus: null, pathMode: false, a: null, b: null, path: null, pathSet: null, q: "", hits: [], type: "", onlyAbn: false, rotate: !reduce, heavy: q.get("heavy") === "1"};
if (q.get("lang") === "en") S.lang = "en";
let G, col = {}, V3 = null, fps = 0, frames = 0, fpsAt = 0;

const pos = n => ({x: n.x * SC, y: -n.y * SC, z: n.z * SC});
const data = { nodes: sky.nodes.map(n => { const p = pos(n); return {id: n.i, n, x: p.x, y: p.y, z: p.z, fx: p.x, fy: p.y, fz: p.z}; }),
               links: sky.edges.map(([a, b, f]) => ({source: a, target: b, f, a, b})) };
const health = n => W.health(n, 0, store);
const tone = n => { const h = health(n); return h === "critical" ? "red" : h === "warning" ? "amber" : h === "notice" ? (n.hot.tone === "violet" ? "violet" : "mint") : null; };
/* is this resource outside what is being looked at right now? (a path beats a focus beats the filters) */
function dim(n){
  if (P.pathSet) return !P.pathSet.has(n.i);
  if (P.focus) return !P.focus.has(n.i);
  if (P.type && n.type !== P.type) return true;
  if (P.onlyAbn && health(n) === "unknown") return true;
  return false;
}
const onPath = l => P.path && P.path.some((i, k) => k && ((P.path[k - 1] === l.a && i === l.b) || (P.path[k - 1] === l.b && i === l.a)));
const ofSel = l => P.sel && !P.pathSet && (l.a === P.sel.i || l.b === P.sel.i);

function recolor(){
  const cs = getComputedStyle(document.body), g = k => cs.getPropertyValue(k).trim();
  col = {star: g("--star"), amber: g("--amber"), mint: g("--mint"), red: g("--red"), violet: g("--violet"), chalk: g("--chalk"), dim: g("--dim")};
}
const nodeColor = d => { const n = d.n, tn = tone(n); if (dim(n)) return `rgba(${col.star},.05)`; return tn ? col[tn] : n.hub ? `rgba(${col.star},.95)` : `rgba(${col.star},.6)`; };
const nodeVal = d => { const n = d.n; return tone(n) ? 16 : n.hub === 2 ? 12 : n.hub ? 5 : 1.4; };
const linkColor = l => {
  if (onPath(l)) return col.mint;
  if (ofSel(l)) return col.chalk;
  const off = dim(sky.nodes[l.a]) || dim(sky.nodes[l.b]);
  if (off) return `rgba(${col.star},.03)`;
  return l.f & 2 ? col.violet : `rgba(${col.star},${l.f & 4 ? .1 : l.f & 1 ? .4 : .28})`;
};
function restyle(){
  G.nodeColor(nodeColor).nodeVal(nodeVal).linkColor(linkColor)
   .linkWidth(l => onPath(l) ? 2.2 : ofSel(l) ? 1 : 0)
   .linkDirectionalParticles(l => onPath(l) ? 4 : ofSel(l) ? 2 : 0);
  panels();
}

/* ── the engine ────────────────────────────────────────────────────────── */
function init(){
  recolor();
  const el = $("#g3d");
  try { G = new ForceGraph3D(el, {controlType: "orbit"}); } catch (e){ G = ForceGraph3D({controlType: "orbit"})(el); }
  G.backgroundColor("rgba(0,0,0,0)").showNavInfo(false).enableNodeDrag(false)
   .nodeRelSize(2.1).nodeResolution(6).nodeOpacity(1).nodeLabel(() => "")
   .linkOpacity(1).linkDirectionalParticleSpeed(.006).linkDirectionalParticleWidth(2.4).linkDirectionalParticleColor(l => onPath(l) ? col.mint : col.chalk)
   .cooldownTicks(0).warmupTicks(0)
   .onNodeClick(d => click(d.n)).onBackgroundClick(() => { if (!P.pathMode) select(null); })
   .onNodeHover(d => { el.style.cursor = d ? "pointer" : "grab"; const tip = $("#tip");
      if (!d){ tip.hidden = true; return; } tip.textContent = d.n.name + "　" + t("type." + d.n.type) + "　" + t("health." + health(d.n)); tip.hidden = false; })
   .graphData(data);
  el.addEventListener("pointermove", e => { const tip = $("#tip"); tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px"; });
  el.addEventListener("pointerdown", () => { if (P.rotate){ P.rotate = false; applyRotate(); panels(); } });      // taking the map in hand stops the turning
  window.addEventListener("resize", () => G.width(innerWidth).height(innerHeight));
  V3 = G.camera().position.constructor;
  home(0); applyRotate(); restyle(); if (P.heavy) heavy(true);
  requestAnimationFrame(frame);
}
const applyRotate = () => { const c = G.controls(); c.autoRotate = P.rotate; c.autoRotateSpeed = .45; };
function home(ms = 900){ G.cameraPosition({x: 0, y: -140, z: innerWidth < 760 ? 1500 : 1050}, {x: 0, y: 0, z: 0}, ms); }
/* fly towards a resource, stopping well short of it: close enough to see its links, far enough to see where it sits */
function flyTo(n, ms = 1000){ const p = pos(n), r = Math.hypot(p.x, p.y, p.z) || 1, k = 1 + 400 / r; G.cameraPosition({x: p.x * k, y: p.y * k, z: p.z * k + (r < 80 ? 400 : 0)}, p, ms); }

/* The original component gives every node its own group of meshes (a core sphere and a glow sphere, plus a text texture).
   This switch does the same with two spheres per resource, to show what that costs at our size. */
function heavy(on){
  P.heavy = on;
  if (!on){ G.nodeThreeObject(null); restyle(); return; }
  let mesh = null; G.scene().traverse(o => { if (!mesh && o.isMesh && o.geometry && o.geometry.type === "SphereGeometry") mesh = o; });
  if (!mesh){ P.heavy = false; return; }
  const Mesh = mesh.constructor, Geo = mesh.geometry.constructor, Mat = mesh.material.constructor, Obj = Object.getPrototypeOf(G.scene().constructor);
  G.nodeThreeObject(d => {
    const r = Math.cbrt(nodeVal(d)) * 2.1, g = new Obj(), c = nodeColor(d);
    g.add(new Mesh(new Geo(r, 24, 18), new Mat({color: c.startsWith("#") ? c : `rgb(${col.star})`, transparent: true, opacity: .95})));
    g.add(new Mesh(new Geo(r * 1.6, 16, 12), new Mat({color: c.startsWith("#") ? c : `rgb(${col.star})`, transparent: true, opacity: .12, side: 1})));
    return g;
  });
  panels();
}

/* ── labels and rings: plain page elements laid over the canvas, for the few resources that need a name ───────── */
function marks(){ const out = new Map(); sky.hot.forEach(h => { if (W.active(h, 0, store)) out.set(h.node.i, h.node); });
  P.hits.forEach(n => out.set(n.i, n)); (P.path || []).forEach(i => out.set(i, sky.nodes[i]));
  [P.b, P.a, P.sel].forEach(n => { if (n){ out.delete(n.i); out.set(n.i, n); } });               // the ones being looked at are drawn last, so their names stay on top
  return [...out.values()]; }
function frame(ts){
  frames++; if (ts - fpsAt >= 1000){ fps = Math.round(frames * 1000 / (ts - fpsAt)); frames = 0; fpsAt = ts; const f = $("#p3fps"); if (f) f.textContent = t("p3.fps", {n: fps}); }
  const cam = G.camera(), cbox = $("#clabels");
  NF.seed.clusters.forEach((c, k) => {                      // the cluster names float above each cluster
    let el = cbox.children[k]; if (!el){ cbox.insertAdjacentHTML("beforeend", `<div class="c3"></div>`); el = cbox.children[k]; }
    const v = new V3(c.cx * SC, -(c.cy - c.sp * 1.75) * SC, (c.cz || 0) * SC).project(cam);
    el.hidden = v.z > 1 || !!(P.pathSet || P.sel || P.focus); if (el.hidden) return;          // names of clusters are for the overview only
    el.style.transform = `translate(${(v.x + 1) / 2 * innerWidth}px,${(1 - v.y) / 2 * innerHeight}px) translate(-50%,-50%)`; const name = tx(c.name); if (el.textContent !== name) el.textContent = name;
  });
  const box = $("#labels"), list = marks(), have = box.children;
  while (have.length < list.length) box.insertAdjacentHTML("beforeend", `<div class="l3"><i></i><span></span></div>`);
  for (let k = 0; k < have.length; k++){
    const el = have[k], n = list[k]; if (!n){ el.hidden = true; continue; }
    const p = pos(n), v = new V3(p.x, p.y, p.z).project(cam), off = dim(n) && n !== P.sel;
    if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1){ el.hidden = true; continue; }
    const tn = tone(n), sel = n === P.sel || n === P.a;
    el.hidden = false; el.style.transform = `translate(${(v.x + 1) / 2 * innerWidth}px,${(1 - v.y) / 2 * innerHeight}px)`;
    el.className = "l3" + (tn ? " t-" + tn : "") + (sel ? " sel" : "") + (off ? " off" : "");
    if (el.dataset.i !== String(n.i)){ el.dataset.i = n.i; el.lastChild.textContent = n.name; }
  }
  requestAnimationFrame(frame);
}

/* ── choosing ──────────────────────────────────────────────────────────── */
function select(n){ P.sel = n; if (P.focus) P.focus = n ? W.around(sky, n, 1) : null; if (n) flyTo(n); restyle(); }
function click(n){
  if (!P.pathMode) return select(n);
  if (!P.a || P.b){ P.a = n; P.b = null; P.path = null; P.pathSet = null; }
  else if (n !== P.a){ P.b = n; P.path = W.path(sky, P.a, P.b); P.pathSet = P.path ? new Set(P.path) : null; }
  restyle();
}
function setPath(a, b){ P.pathMode = true; P.focus = null; P.sel = null; P.a = a; P.b = b; P.path = W.path(sky, a, b); P.pathSet = P.path ? new Set(P.path) : null; restyle(); if (P.path) home(); }
function exitPath(){ P.pathMode = false; P.a = P.b = P.path = P.pathSet = null; restyle(); }

/* ── panels ────────────────────────────────────────────────────────────── */
const dot = n => { const tn = tone(n); return `<i class="hdot" style="background:${tn ? `var(--${tn})` : "rgb(var(--star))"}"></i>`; };
function panels(){
  const counts = {}; sky.nodes.forEach(n => { counts[n.type] = (counts[n.type] || 0) + 1; });
  const abn = W.abnormal(sky, 0, store), shown = sky.nodes.filter(n => !dim(n)).length;
  $("#p3title").innerHTML = `<b>${t("p3.title")}</b><span>${t("p3.sub")}</span>`;
  $("#p3back").textContent = t("p3.back"); $("#p3theme").textContent = t("theme." + S.theme); $("#p3lang").textContent = S.lang === "zh" ? "English" : "中文";
  const typing = document.activeElement && document.activeElement.id === "p3q";
  if (!typing) $("#p3tools").innerHTML = `<label class="wsearch"><input class="field" id="p3q" type="search" autocomplete="off" spellcheck="false" value="${esc(P.q)}" placeholder="${t("world.search")}" aria-label="${t("world.search")}"><kbd>F</kbd></label>
    <div id="wres" role="listbox"></div>
    <button class="chip-btn" data-do="p3abn" aria-pressed="${P.onlyAbn}">${t("world.onlyAbnormal")}</button><span class="wcount num">${t("world.showing", {n: shown.toLocaleString("en-US"), total: sky.nodes.length.toLocaleString("en-US")})}</span>
    <div class="p3types">${NF.TYPES.map(ty => `<button data-do="p3type" data-v="${ty.id}" aria-pressed="${P.type === ty.id}"><span>${t("type." + ty.id)}</span><small class="num">${counts[ty.id] || 0}</small></button>`).join("")}</div>`;
  hits();
  $("#p3abnList").innerHTML = `<h2>${t("world.now")}</h2><div class="abn num">${abn.length}<small>${t("world.abnormal")}</small></div>
    <ul class="abnlist">${abn.map(h => { const it = store.get(h.ref); return `<li><button data-do="p3node" data-i="${h.node.i}">${dot(h.node)}<span>${esc(h.name)}</span><small class="num">${it ? it.ref : h.ref.replace(/^([IC])/, "$1#")}</small></button></li>`; }).join("")}</ul>`;
  $("#p3bar").innerHTML = `<button class="btn sm" data-do="p3focus" aria-pressed="${!!P.focus}" ${P.sel ? "" : "disabled"}><span class="t">${t("p3.focus")}</span><kbd>G</kbd></button>
    <button class="btn sm" data-do="p3path" aria-pressed="${P.pathMode}"><span class="t">${t("p3.path")}</span><kbd>L</kbd></button>
    <button class="btn sm" data-do="p3rotate" aria-pressed="${P.rotate}"><span class="t">${t("p3.rotate")}</span><kbd>R</kbd></button>
    <button class="btn sm" data-do="p3home"><span class="t">${t("p3.home")}</span><kbd>0</kbd></button>
    <span class="spacer"></span><span class="p3perf"><span id="p3fps" class="num">${t("p3.fps", {n: fps})}</span>
      <button class="chip-btn" data-do="p3heavy" aria-pressed="${P.heavy}" title="${t("p3.heavyTip")}">${t(P.heavy ? "p3.heavyOn" : "p3.heavyOff")}</button></span>`;
  const hint = $("#p3hint"); hint.hidden = !P.pathMode;
  if (P.pathMode){ const name = n => `<b>${esc(n.name)}</b>`;
    hint.innerHTML = !P.a ? t("p3.pathPick1") : !P.b ? t("p3.pathPick2", {a: name(P.a)})
      : P.path ? `${NF.prov(true)}${t("p3.pathFound", {n: P.path.length - 1})}　<span class="chain">${P.path.map(i => esc(sky.nodes[i].name)).join(" → ")}</span>` : `${NF.prov(true)}${t("p3.pathNone", {a: name(P.a), b: name(P.b)})}`;
    hint.innerHTML += `　<button class="btn sm" data-do="p3demo"><span class="t">${t("p3.pathDemo")}</span></button><button class="btn sm quiet" data-do="p3path"><span class="t">${t("p3.pathExit")}</span><kbd>Esc</kbd></button>`; }
  card();
}
function hits(){
  P.hits = W.search(sky, P.q, ctx); const el = $("#wres"); if (!el) return;
  el.innerHTML = !P.q.trim() ? "" : !P.hits.length ? `<p class="note" style="margin:6px 2px 0">${t("world.noMatch")}</p>`
    : P.hits.map(n => `<button role="option" data-do="p3node" data-i="${n.i}">${dot(n)}<span>${esc(n.name)}</span><small>${t("type." + n.type)}</small></button>`).join("");
}
function card(){
  const el = $("#nodecard"), n = P.sel; if (!n || P.pathMode){ el.hidden = true; return; }
  const h = health(n), it = n.hot && store.get(n.hot.ref), open = h !== "unknown", nb = W.adj(sky)[n.i].map(([j, f]) => ({node: sky.nodes[j], f})), llm = nb.filter(x => x.f & 2).length;
  const acct = NF.seed.accounts.find(a => a.id === n.account), ref = n.hot ? (it ? it.ref : n.hot.ref.replace(/^([IC])/, "$1#")) : "";
  const rel = x => x.f & 4 ? t((x.node.hub || 0) > (n.hub || 0) ? "p3.in" : "p3.holds") : x.f & 2 ? t("node.inferred") : x.f & 1 ? t("p3.cross") : t("p3.linked");
  el.innerHTML = `<button class="x" data-do="p3close" aria-label="${t("peek.close")}">×</button><h3>${esc(n.name)}</h3>
    <div class="sub">${t("type." + n.type)}　·　${acct ? esc(tx(acct.name)) : ""}　·　${n.region}</div>
    <p>${NF.prov(true)}${dot(n)}<b>${t("health." + h)}</b>${open ? `　<span class="num">${ref}</span>${it ? "　" + esc(tx(it.title)) : ""}` : ""}</p>
    ${open ? "" : `<p class="note">${t("node.none")}</p>`}
    <p>${NF.prov(true)}${esc(t("node.links", {n: nb.length}))}${llm ? esc(t("node.linksLlm", {n: llm})) : ""}</p>
    <ul class="nb">${nb.slice(0, 7).map(x => `<li><button data-do="p3node" data-i="${x.node.i}">${dot(x.node)}<span>${esc(x.node.name)}</span><small>${rel(x)}</small></button></li>`).join("")}</ul>
    ${nb.length > 7 ? `<p class="note">${esc(t("p3.more", {n: nb.length - 7}))}</p>` : ""}
    <div class="acts">${it && it.status === "waiting" ? `<a class="btn primary sm" href="index.html#/decide/${it.id}"><span class="t">${t("node.go")}</span></a>` : ""}
      ${it ? `<a class="btn sm" href="index.html#/story/${it.id}"><span class="t">${t("act.story")}</span></a>` : ""}
      <button class="btn sm" data-do="p3from"><span class="t">${t("p3.pathFrom")}</span></button></div>`;
  el.hidden = false;
}

/* ── wiring ────────────────────────────────────────────────────────────── */
const on = {
  p3node: el => { const n = sky.nodes[+el.dataset.i]; if (P.pathMode) click(n); else select(n); },
  p3close: () => select(null),
  p3abn: () => { P.onlyAbn = !P.onlyAbn; restyle(); },
  p3type: el => { P.type = P.type === el.dataset.v ? "" : el.dataset.v; restyle(); },
  p3focus: () => { if (!P.sel) return; P.focus = P.focus ? null : W.around(sky, P.sel, 1); restyle(); },
  p3path: () => { if (P.pathMode) exitPath(); else { P.pathMode = true; P.focus = null; P.a = P.sel; P.sel = null; restyle(); } },
  p3from: () => { P.pathMode = true; P.focus = null; P.a = P.sel; P.b = null; P.sel = null; restyle(); },
  p3demo: () => { const by = r => sky.hot.find(h => h.ref === r).node; setPath(by("I12"), by("I8")); },
  p3rotate: () => { P.rotate = !P.rotate; applyRotate(); panels(); },
  p3home: () => { home(); },
  p3heavy: () => heavy(!P.heavy),
  p3theme: () => { S.theme = S.theme === "night" ? "day" : "night"; document.body.dataset.theme = S.theme; recolor(); restyle(); },
  p3lang: () => { S.lang = S.lang === "zh" ? "en" : "zh"; document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en"; panels(); },
};
document.addEventListener("click", e => { const el = e.target.closest("[data-do]"); if (el && on[el.dataset.do]) on[el.dataset.do](el); });
document.addEventListener("input", e => { if (e.target.id === "p3q"){ P.q = e.target.value; hits(); } });
document.addEventListener("keydown", e => {
  const inField = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.key === "Escape"){ if (inField) return document.activeElement.blur(); if (P.pathMode) return exitPath(); if (P.focus){ P.focus = null; return restyle(); } if (P.sel) return select(null); return home(); }
  if (inField){ if (e.key === "Enter" && e.target.id === "p3q" && P.hits[0]){ const n = P.hits[0]; e.target.blur(); if (P.pathMode) click(n); else select(n); } return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "f"){ e.preventDefault(); const i = $("#p3q"); i.focus(); i.select(); }
  else if (k === "g") on.p3focus(); else if (k === "l") on.p3path(); else if (k === "r") on.p3rotate(); else if (k === "0") on.p3home(); else if (k === "t") on.p3theme();
});
NF.p3 = {P, sky, store, init, get graph(){ return G; }, get fps(){ return fps; }, setPath, select, heavy};
if (typeof ForceGraph3D === "undefined"){ $("#g3d").innerHTML = `<div class="state failed" style="padding-top:30vh"><div class="big">${t("p3.noLib")}</div></div>`; } else init();
})();
