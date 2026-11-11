/* new-UI-face — the «全景» lens: every resource on one map. Find one, filter them, open one, and go back in time.
   The rules (health, filters, search, time steps) are in model-world.js; the drawing is in sky.js; this file is the panels. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, W = NF.world;
const F = S.world = {q: "", account: "", type: "", onlyAbnormal: false, sel: null, playing: false};   // what the lens is showing
const ctx = () => ({hoursAgo: S.hoursAgo, store: NF.store});
const TONE_VAR = {critical: "red", warning: "amber", notice: "mint", unknown: "star"};
const toneOf = n => { const h = W.health(n, S.hoursAgo, NF.store); return h === "notice" && n.hot && n.hot.tone === "violet" ? "violet" : TONE_VAR[h]; };
const dot = n => { const v = toneOf(n); return `<i class="hdot" style="background:${v === "star" ? "rgb(var(--star))" : `var(--${v})`}"></i>`; };
let timer = null;

function applyFilter(){
  const sky = NF.sky.data, on = F.account || F.type || F.onlyAbnormal, c = ctx();
  if (!on){ NF.sky.view.faint = null; return sky.nodes.length; }
  const faint = new Set(); sky.nodes.forEach(n => { if (!W.match(n, F, c)) faint.add(n.i); });
  NF.sky.view.faint = faint; return sky.nodes.length - faint.size;
}
function renderTools(shown){
  const total = NF.sky.data.nodes.length, opt = (v, label, cur) => `<option value="${v}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
  $("#wtools").innerHTML = `<label class="wsearch"><input class="field" id="wq" type="search" autocomplete="off" spellcheck="false" value="${esc(F.q)}" placeholder="${t("world.search")}" aria-label="${t("world.search")}"><kbd>F</kbd></label>
    <div id="wres" role="listbox" aria-label="${t("world.results")}"></div>
    <div class="wf"><select class="field" id="wAcct" aria-label="${t("fact.account")}">${opt("", t("world.allAccounts"), F.account)}${NF.seed.accounts.map(a => opt(a.id, tx(a.name), F.account)).join("")}</select>
      <select class="field" id="wType" aria-label="${t("node.type")}">${opt("", t("world.allTypes"), F.type)}${NF.TYPES.map(ty => opt(ty.id, t("type." + ty.id), F.type)).join("")}</select></div>
    <button class="chip-btn" data-do="wAbn" aria-pressed="${F.onlyAbnormal}">${t("world.onlyAbnormal")}</button>
    <span class="wcount num">${t("world.showing", {n: shown.toLocaleString("en-US"), total: total.toLocaleString("en-US")})}</span>`;
  renderHits();
}
function renderHits(){
  const hits = W.search(NF.sky.data, F.q, ctx()); NF.sky.view.hits = hits;
  const el = $("#wres"); if (!el) return;
  el.innerHTML = !F.q.trim() ? "" : !hits.length ? `<p class="note" style="margin:6px 2px 0">${t("world.noMatch")}</p>`
    : hits.map(n => `<button role="option" data-do="wNode" data-i="${n.i}">${dot(n)}<span>${esc(n.name)}</span><small>${t("type." + n.type)}</small></button>`).join("");
}
function renderHappen(){
  const h = S.hoursAgo, c = ctx(), narrow = innerWidth <= 760;
  const abn = W.abnormal(NF.sky.data, h, NF.store).filter(x => W.match(x.node, F, c));
  const list = NF.store.events.filter(e => e.h >= h).sort((a, b) => a.h - b.h).slice(0, narrow ? 4 : 8);
  $("#happen").innerHTML = `<h2>${h === 0 ? t("world.now") : t("world.backTo", {t: NF.clockAt(h)})}</h2><div class="abn num">${abn.length}<small>${t("world.abnormal")}</small></div>
    ${abn.length ? `<ul class="abnlist">${abn.map(x => { const it = NF.store.get(x.ref); return `<li><button data-do="wNode" data-i="${x.node.i}">${dot(x.node)}<span>${esc(x.name)}</span><small class="num">${it ? it.ref : x.ref.replace(/^([IC])/, "$1#")}</small></button></li>`; }).join("")}</ul>`
      : `<p class="note">${t("world.noneAbnormal")}</p>`}
    <h2 style="margin-top:12px">${t("world.events")}</h2>
    <ul class="evlist">${list.map(e => `<li class="${e.cause ? "cause" : ""}"><button data-do="wEvent" data-h="${e.h}"><time>${NF.clockAt(e.h)}</time><span>${esc(NF.eventText(e))}${e.cause ? "　" + t("world.cause") : ""}</span></button></li>`).join("")}</ul>`;
}
function renderScrub(){
  const h = S.hoursAgo, ev = NF.store.events;
  $("#scrubCtl").innerHTML = `<button class="btn sm" data-do="wStep" data-d="-1" aria-label="${t("world.prevEvent")}"><span class="t">◂</span><kbd>[</kbd></button>
    <button class="btn sm" data-do="wPlay"><span class="t">${t(F.playing ? "world.pause" : "world.play")}</span><kbd>P</kbd></button>
    <button class="btn sm" data-do="wStep" data-d="1" aria-label="${t("world.nextEvent")}"><span class="t">▸</span><kbd>]</kbd></button>
    <b id="scrubLbl">${h === 0 ? t("world.nowAt", {t: NF.clockAt(0)}) : t("world.ago", {t: NF.clockAt(h), d: NF.fmtWait(Math.max(1, Math.round(h * 60)))})}</b>
    <span class="spacer"></span>${h > 0 ? `<button class="btn sm" data-do="wNow"><span class="t">${t("world.toNow")}</span><kbd>0</kbd></button>` : `<span class="built">${t("world.built", {t: NF.clockAt(NF.seed.watch.lastScanMin / 60)})}</span>`}
    <a class="btn sm quiet" href="preview-3d.html"><span class="t">${t("world.open3d")}</span></a>`;
  $("#scrubTicks").innerHTML = ev.filter(e => e.h <= 24).map(e => `<i class="${e.k}${e.cause ? " cause" : ""}" style="left:${100 - e.h / 24 * 100}%"></i>`).join("");
  $("#scrub").setAttribute("aria-label", t("world.time")); $("#scrub").value = 240 - h * 10;
  const past = $("#wpast"); past.hidden = h === 0;
  if (h > 0) past.innerHTML = `${NF.prov(true)}${esc(t("world.past", {t: NF.clockAt(h), d: NF.fmtWait(Math.max(1, Math.round(h * 60)))}))}`;
}
function renderLegend(){
  $("#legend").innerHTML = [["red", "legend.critical"], ["amber", "legend.waiting"], ["mint", "legend.agent"], ["violet", "legend.change"]].map(([c, k]) => `<span><i style="background:var(--${c})"></i>${t(k)}</span>`).join("")
    + `<span><i style="background:rgb(var(--star));opacity:.6"></i>${t("legend.none")}</span><span><i class="dash"></i>${t("legend.llm")}</span>`;
}
function nodeCard(){
  const el = $("#nodecard"), n = F.sel; NF.sky.view.sel = n || null;
  if (!n){ el.hidden = true; return; }
  const h = S.hoursAgo, health = W.health(n, h, NF.store), it = n.hot && NF.store.get(n.hot.ref), open = health !== "unknown", nb = NF.sky.neighbours(n), llm = nb.filter(x => x.llm).length;
  const acct = NF.seed.accounts.find(a => a.id === n.account), ref = n.hot ? (it ? it.ref : n.hot.ref.replace(/^([IC])/, "$1#")) : "";
  el.innerHTML = `<button class="x" data-do="wClose" aria-label="${t("peek.close")}">×</button><h3>${esc(n.name)}</h3>
    <div class="sub">${t("type." + n.type)}　·　${acct ? esc(tx(acct.name)) : ""}　·　${n.region}</div>
    <p>${NF.prov(true)}${h > 0 ? esc(t("world.at", {t: NF.clockAt(h)})) : ""}${dot(n)}<b>${t("health." + health)}</b>${open ? `　<span class="num">${ref}</span>${it ? "　" + esc(tx(it.title)) : ""}` : ""}</p>
    ${open ? "" : `<p class="note">${t("node.none")}</p>`}
    <p>${NF.prov(true)}${esc(t("node.links", {n: nb.length}))}${llm ? esc(t("node.linksLlm", {n: llm})) : ""}</p>
    <ul class="nb">${nb.slice(0, 6).map(x => `<li><button data-do="wNode" data-i="${x.node.i}">${dot(x.node)}<span>${esc(x.node.name)}</span><small>${t("type." + x.node.type)}${x.llm ? "　" + t("node.inferred") : ""}</small></button></li>`).join("")}</ul>
    <p class="note">${NF.prov(true)}${esc(t("node.seen", {t: NF.clockAt(NF.seed.watch.lastScanMin / 60)}))}</p>
    <div class="acts">${it && it.status === "waiting" && h === 0 ? `<button class="btn primary sm" data-do="openItem" data-id="${it.id}"><span class="t">${t("node.go")}</span></button>` : ""}
      ${it ? `<button class="btn sm" data-do="story" data-id="${it.id}"><span class="t">${t("act.story")}</span></button>` : ""}
      <button class="btn sm quiet" data-do="wAsk"><span class="t">${t("act.ask")}</span><kbd>E</kbd></button></div>`;
  el.hidden = false;
}
function render(){
  const ready = S.view === "ready";
  $("#wstate").hidden = ready; ["#wleft", "#legend", "#scrubCard"].forEach(s => { $(s).hidden = !ready; });
  NF.sky.view.blank = !ready;
  if (!ready){
    $("#nodecard").hidden = true; $("#wpast").hidden = true; stop();
    $("#wstate").innerHTML = S.view === "empty" ? `<div class="state"><div class="big">${t("world.empty.big")}</div><p>${t("world.empty.p")}</p></div>` : NF.stateBlock(S.view, "world.failed.p");
    return;
  }
  const shown = applyFilter(); renderTools(shown); renderHappen(); renderScrub(); renderLegend(); nodeCard();
}
/* the store or a filter changed: redraw the panels, but never the search box while someone is typing in it */
const refresh = () => {
  if (S.view !== "ready" || $("#wstate").hidden === false) return render();
  const shown = applyFilter(), typing = document.activeElement && document.activeElement.id === "wq";
  if (typing){ renderHits(); const c = $(".wcount"); if (c) c.textContent = t("world.showing", {n: shown.toLocaleString("en-US"), total: NF.sky.data.nodes.length.toLocaleString("en-US")}); } else renderTools(shown);
  renderHappen(); renderScrub(); nodeCard();
};

function select(n, fly = true){ F.sel = n; if (n && fly) NF.sky.flyTo(n); nodeCard(); }
function setTime(h){ S.hoursAgo = Math.max(0, Math.min(24, h)); applyFilter(); renderHappen(); renderScrub(); renderHits(); nodeCard(); }
function stop(){ if (timer){ clearInterval(timer); timer = null; } F.playing = false; }
function play(){
  if (F.playing){ stop(); renderScrub(); return; }
  F.playing = true; if (S.hoursAgo === 0) S.hoursAgo = 24;                       // from a day ago up to now, in about 12 seconds
  timer = setInterval(() => { if (S.lens !== "world"){ stop(); return; } const h = Math.max(0, +(S.hoursAgo - .1).toFixed(2)); if (h === 0) stop(); setTime(h); }, 50);
  renderScrub();
}

Object.assign(NF.on, {
  openItem: el => { S.filter = "all"; S.cur = el.dataset.id; NF.setLens("decide"); },
  wNode: el => select(NF.sky.data.nodes[+el.dataset.i]),
  wClose: () => { select(null); NF.sky.home(); },
  wAbn: () => { F.onlyAbnormal = !F.onlyAbnormal; refresh(); },
  wEvent: el => { stop(); setTime(+el.dataset.h); },
  wStep: el => { stop(); setTime(W.stepEvent(NF.store.events, S.hoursAgo, +el.dataset.d)); },
  wPlay: () => play(),
  wNow: () => { stop(); setTime(0); },
  wAsk: () => { const i = $("#cmd"); i.value = F.sel ? `@${F.sel.name} ` : ""; i.focus(); },
});

NF.screens.world = {
  render, refresh,
  key(e, k){
    if (S.view !== "ready") return;
    if (k === "f"){ e.preventDefault(); const q = $("#wq"); q.focus(); q.select(); return; }
    if (k === "p") return play();
    if (k === "[" || k === ","){ stop(); return setTime(W.stepEvent(NF.store.events, S.hoursAgo, -1)); }
    if (k === "]" || k === "."){ stop(); return setTime(W.stepEvent(NF.store.events, S.hoursAgo, 1)); }
    if (k === "0"){ stop(); return setTime(0); }
    if (k === "e" && F.sel) { e.preventDefault(); return NF.on.wAsk(); }
  },
  /* Esc: first the open resource, then a moved camera. Returns whether it used the key. */
  esc(){ if (F.sel){ NF.on.wClose(); return true; } if (NF.sky.view.free){ NF.sky.home(); return true; } return false; },
  init(){
    const el = $("#world"), tip = $("#tip"); let drag = null;
    $("#scrub").addEventListener("input", e => { stop(); setTime((240 - +e.target.value) / 10); });
    el.addEventListener("input", e => { if (e.target.id === "wq"){ F.q = e.target.value; renderHits(); } });
    el.addEventListener("change", e => { if (e.target.id === "wAcct"){ F.account = e.target.value; refresh(); } if (e.target.id === "wType"){ F.type = e.target.value; refresh(); } });
    el.addEventListener("keydown", e => { if (e.target.id === "wq" && e.key === "Enter"){ const hit = NF.sky.view.hits[0]; if (hit){ select(hit); e.target.blur(); } } });
    /* gestures on the map itself (the section, wherever no panel covers it) */
    el.addEventListener("pointerdown", e => { if (e.target !== el || S.view !== "ready") return; drag = {x: e.clientX, y: e.clientY, moved: false}; el.setPointerCapture(e.pointerId); });
    el.addEventListener("pointermove", e => {
      if (drag){ const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (drag.moved || Math.hypot(dx, dy) > 4){ drag.moved = true; NF.sky.panBy(dx, dy); drag.x = e.clientX; drag.y = e.clientY; el.style.cursor = "grabbing"; tip.hidden = true; } return; }
      if (e.target !== el || S.view !== "ready"){ tip.hidden = true; el.style.cursor = ""; return; }
      const n = NF.sky.pick(e.clientX, e.clientY); if (!n){ tip.hidden = true; el.style.cursor = "grab"; return; }
      tip.textContent = n.name + "　" + t("type." + n.type) + "　" + t("health." + W.health(n, S.hoursAgo, NF.store));
      tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px"; tip.hidden = false; el.style.cursor = "pointer";
    });
    el.addEventListener("pointerup", e => { const d = drag; drag = null; el.style.cursor = ""; if (!d || d.moved) return; const n = NF.sky.pick(e.clientX, e.clientY); select(n || null, false); });
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
    el.addEventListener("wheel", e => { if (e.target !== el || S.view !== "ready") return; e.preventDefault(); NF.sky.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * .0016)); }, {passive: false});
  },
};
})();
