/* new-UI-face — the «全景» lens: every resource on one map, in two views (flat and 3D) of ONE state.
   What to show is worked out once, by NF.world.scene (model-world.js); both views draw that result and the panels read their
   numbers from it, so the two views cannot disagree. After every change the lens asks the view on screen what it actually
   drew and compares (NF.world.reconcile): the «数据核对» line says whether the picture matches the data. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, W = NF.world;
/* what the person asked for — the whole state of the lens, apart from the hour (S.hoursAgo) */
const F = S.world = {view: "2d", q: "", account: "", type: "", onlyAbnormal: false, sel: null, focus: false, pathMode: false, a: null, b: null, playing: false};
const ctx = () => ({hoursAgo: S.hoursAgo, store: NF.store});
const TONE_VAR = {critical: "red", warning: "amber", notice: "mint"};
const toneOf = n => { const h = W.health(n, S.hoursAgo, NF.store); return h === "notice" && n.hot && n.hot.tone === "violet" ? "violet" : TONE_VAR[h] || null; };
const dot = n => { const v = toneOf(n), gone = W.health(n, S.hoursAgo, NF.store) === "gone"; return `<i class="hdot${gone ? " gone" : ""}" style="${gone ? "" : `background:${v ? `var(--${v})` : "rgb(var(--star))"}`}"></i>`; };
const nm = n => W.health(n, S.hoursAgo, NF.store) === "gone" ? `<s>${esc(n.name)}</s>` : esc(n.name);
const num = v => v.toLocaleString("en-US");
const is3d = () => F.view === "3d" && NF.sky3.ready;
let timer = null, sc = null, checkT = null;

/* ── one result, handed to whichever view is on screen ─────────────────── */
function compute(){
  sc = W.scene(NF.sky.data, F, ctx());
  NF.sky.apply(sc, F.pathMode ? null : F.sel); NF.sky.view.off = is3d();
  if (is3d()) NF.sky3.apply(sc, F.pathMode ? null : F.sel);
  clearTimeout(checkT); checkT = setTimeout(check, 260);        // the views draw on their next frame: ask them afterwards
  return sc;
}
/* the picture against the data */
function check(){
  const el = $("#wcheck"); if (!el || !sc || S.lens !== "world" || S.view !== "ready") return;
  const view = is3d() ? "3d" : "2d", bad = W.reconcile(sc, view, view === "3d" ? NF.sky3.stats() : NF.sky.stats()), T = sc.totals;
  el.className = "wcheck card" + (bad.length ? " bad" : "");
  el.dataset.ok = bad.length ? "0" : "1";
  el.innerHTML = `<h2>${t("check.title")}</h2>
    <p>${NF.prov(true)}${esc(t("check.totals", {present: num(T.present), gone: T.gone, links: num(T.links), inferred: T.inferred}))}</p>
    <p>${NF.prov(true)}${esc(t("check.fresh", {t: NF.clockAt(NF.seed.watch.lastScanMin / 60)}))}</p>
    ${bad.length ? `<p class="mis" role="alert">${t("check.bad")}${bad.map(m => esc(t("check.item", {what: t("check." + m.what), want: num(m.want), got: num(m.got)}))).join("；")}</p>`
      : `<p class="ok">${NF.prov(true)}${esc(t("check.ok", {view: t("view." + view), n: num(W.expected(sc, view).bright), r: sc.rings.length, l: num(W.expected(sc, view).links)}))}</p>`}`;
}

/* ── panels ────────────────────────────────────────────────────────────── */
function renderTools(){
  const opt = (v, label, cur) => `<option value="${v}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
  $("#wtools").innerHTML = `<div class="tabs wview" role="tablist" aria-label="${t("view.label")}">${["2d", "3d"].map(v => `<button role="tab" data-do="wView" data-v="${v}" aria-selected="${F.view === v}">${t("view." + v)}</button>`).join("")}<kbd>V</kbd></div>
    <label class="wsearch"><input class="field" id="wq" type="search" autocomplete="off" spellcheck="false" value="${esc(F.q)}" placeholder="${t("world.search")}" aria-label="${t("world.search")}"><kbd>F</kbd></label>
    <div id="wres" role="listbox" aria-label="${t("world.results")}"></div>
    <div class="wf"><select class="field" id="wAcct" aria-label="${t("fact.account")}">${opt("", t("world.allAccounts"), F.account)}${NF.seed.accounts.map(a => opt(a.id, tx(a.name), F.account)).join("")}</select>
      <select class="field" id="wType" aria-label="${t("node.type")}">${opt("", t("world.allTypes"), F.type)}${NF.TYPES.map(ty => opt(ty.id, t("type." + ty.id), F.type)).join("")}</select></div>
    <button class="chip-btn" data-do="wAbn" aria-pressed="${F.onlyAbnormal}">${t("world.onlyAbnormal")}</button>
    <span class="wcount num">${t("world.showing", {n: num(sc.shown), total: num(sc.totals.nodes - sc.gone.size)})}</span>`;
  renderHits();
}
function renderHits(){
  const el = $("#wres"); if (!el) return;
  el.innerHTML = !F.q.trim() ? "" : !sc.hits.length ? `<p class="note" style="margin:6px 2px 0">${t("world.noMatch")}</p>`
    : sc.hits.map(n => `<button role="option" data-do="wNode" data-i="${n.i}">${dot(n)}<span>${nm(n)}</span><small>${t("type." + n.type)}</small></button>`).join("");
}
function renderHappen(){
  const h = S.hoursAgo, narrow = innerWidth <= 760, abn = sc.abnormal;
  const list = NF.store.events.filter(e => e.h >= h).sort((a, b) => a.h - b.h).slice(0, narrow ? 4 : 7);
  $("#happen").innerHTML = `<h2>${h === 0 ? t("world.now") : t("world.backTo", {t: NF.clockAt(h)})}</h2><div class="abn num">${abn.length}<small>${t("world.abnormal")}</small></div>
    ${abn.length ? `<ul class="abnlist">${abn.map(x => { const it = NF.store.get(x.ref); return `<li><button data-do="wNode" data-i="${x.node.i}">${dot(x.node)}<span>${esc(x.name)}</span><small class="num">${it ? it.ref : x.ref.replace(/^([IC])/, "$1#")}</small></button></li>`; }).join("")}</ul>`
      : `<p class="note">${t("world.noneAbnormal")}</p>`}
    ${h === 0 ? `<p class="note ties">${NF.prov(true)}${esc(t("world.ties", {n: sc.ringed.length + sc.quiet.length + sc.offMap.length, ring: sc.ringed.length, quiet: sc.quiet.length, off: sc.offMap.length}))}${sc.offMap.length ? `　<button class="linkish" data-do="lens" data-lens="decide">${t("world.tiesGo")}</button>` : ""}</p>` : ""}
    <h2 style="margin-top:12px">${t("world.events")}</h2>
    <ul class="evlist">${list.map(e => `<li class="${e.cause ? "cause" : ""}"><button data-do="wEvent" data-h="${e.h}"><time>${NF.clockAt(e.h)}</time><span>${esc(NF.eventText(e))}${e.cause ? "　" + t("world.cause") : ""}</span></button></li>`).join("")}</ul>`;
}
function renderScrub(){
  const h = S.hoursAgo, ev = NF.store.events;
  $("#scrubCtl").innerHTML = `<button class="btn sm" data-do="wStep" data-d="-1" aria-label="${t("world.prevEvent")}"><span class="t">◂</span><kbd>[</kbd></button>
    <button class="btn sm" data-do="wPlay"><span class="t">${t(F.playing ? "world.pause" : "world.play")}</span><kbd>P</kbd></button>
    <button class="btn sm" data-do="wStep" data-d="1" aria-label="${t("world.nextEvent")}"><span class="t">▸</span><kbd>]</kbd></button>
    <b id="scrubLbl">${h === 0 ? t("world.nowAt", {t: NF.clockAt(0)}) : t("world.ago", {t: NF.clockAt(h), d: NF.fmtWait(Math.max(1, Math.round(h * 60)))})}</b>
    <span class="spacer"></span>${h > 0 ? `<button class="btn sm" data-do="wNow"><span class="t">${t("world.toNow")}</span><kbd>0</kbd></button>` : ""}
    <button class="btn sm ${F.pathMode ? "on" : ""}" data-do="wPath" aria-pressed="${F.pathMode}"><span class="t">${t("world.path")}</span><kbd>L</kbd></button>
    ${is3d() ? `<button class="btn sm ${NF.sky3.turning ? "on" : ""}" data-do="wTurn" aria-pressed="${NF.sky3.turning}"><span class="t">${t("world.turn")}</span><kbd>R</kbd></button>` : ""}
    <button class="btn sm quiet" data-do="wHome"><span class="t">${t("world.home")}</span><kbd>H</kbd></button>`;
  $("#scrubTicks").innerHTML = ev.filter(e => e.h <= 24).map(e => `<i class="${e.k}${e.cause ? " cause" : ""}" style="left:${100 - e.h / 24 * 100}%"></i>`).join("");
  $("#scrub").setAttribute("aria-label", t("world.time")); $("#scrub").value = 240 - h * 10;
  const past = $("#wpast"); past.hidden = h === 0 || F.pathMode;
  if (h > 0) past.innerHTML = `${NF.prov(true)}${esc(t("world.past", {t: NF.clockAt(h), d: NF.fmtWait(Math.max(1, Math.round(h * 60)))}))}`;
  const hint = $("#whint"); hint.hidden = !F.pathMode;
  if (F.pathMode){ const name = n => `<b>${esc(n.name)}</b>`;
    hint.innerHTML = (!F.a ? t("path.pick1") : !F.b ? t("path.pick2", {a: name(F.a)})
        : sc.path ? `${NF.prov(true)}${t("path.found", {n: sc.path.length - 1})}<span class="chain">${sc.path.map(i => esc(NF.sky.data.nodes[i].name)).join(" → ")}</span>　${t("path.caveat")}` : `${NF.prov(true)}${t("path.none", {a: name(F.a), b: name(F.b)})}`)
      + `　<button class="btn sm" data-do="wPathDemo"><span class="t">${t("path.demo")}</span></button><button class="btn sm quiet" data-do="wPath"><span class="t">${t("path.exit")}</span><kbd>Esc</kbd></button>`; }
}
function renderLegend(){
  $("#legend").innerHTML = [["red", "legend.critical"], ["amber", "legend.waiting"], ["mint", "legend.agent"], ["violet", "legend.change"]].map(([c, k]) => `<span><i style="background:var(--${c})"></i>${t(k)}</span>`).join("")
    + `<span><i style="background:rgb(var(--star));opacity:.6"></i>${t("legend.none")}</span><span><i class="gonei"></i>${t("legend.gone")}</span>
       <span><i class="${is3d() ? "curve" : "dash"}"></i>${t(is3d() ? "legend.llm3d" : "legend.llm")}</span><span><i style="background:var(--mint);width:5px;height:5px"></i>${t("legend.flow")}</span>
       <span class="sch">${t("legend.schematic")}</span>`;
}
function nodeCard(){
  const el = $("#nodecard"), n = F.sel;
  if (!n || F.pathMode){ el.hidden = true; return; }
  const h = S.hoursAgo, health = W.health(n, h, NF.store), it = n.hot && NF.store.get(n.hot.ref), open = !!TONE_VAR[health], nb = W.adj(NF.sky.data)[n.i], llm = nb.filter(x => x[1] & 2).length;
  const acct = NF.seed.accounts.find(a => a.id === n.account), ref = n.hot ? (it ? it.ref : n.hot.ref.replace(/^([IC])/, "$1#")) : "";
  const rel = x => t("rel." + W.relation(x)) + (x[1] & 4 ? t(x[2] ? "rel.holds" : "rel.in") : x[1] & 1 ? t("rel.cross") : "");
  el.innerHTML = `<button class="x" data-do="wClose" aria-label="${t("peek.close")}">×</button><h3>${nm(n)}</h3>
    <div class="sub">${t("type." + n.type)}　·　${acct ? esc(tx(acct.name)) : ""}　·　${n.region}</div>
    <p>${NF.prov(true)}${h > 0 ? esc(t("world.at", {t: NF.clockAt(h)})) : ""}${dot(n)}<b>${t("health." + health)}</b>${open ? `　<span class="num">${ref}</span>${it ? "　" + esc(tx(it.title)) : ""}` : ""}</p>
    ${health === "gone" ? `<p class="note">${NF.prov(true)}${esc(t("node.gone", {t: NF.clockAt(n.gone.h)}))}</p>` : open ? "" : `<p class="note">${t("node.none")}</p>`}
    <p>${NF.prov(true)}${esc(t("node.links", {n: nb.length}))}${llm ? esc(t("node.linksLlm", {n: llm})) : ""}</p>
    <ul class="nb">${nb.slice(0, 7).map(x => { const m = NF.sky.data.nodes[x[0]]; return `<li><button data-do="wNode" data-i="${m.i}">${dot(m)}<span>${nm(m)}</span><small>${rel(x)}</small></button></li>`; }).join("")}</ul>
    ${nb.length > 7 ? `<p class="note">${esc(t("node.more", {n: nb.length - 7}))}</p>` : ""}
    ${health === "gone" ? "" : `<p class="note">${NF.prov(true)}${esc(t("node.seen", {t: NF.clockAt(NF.seed.watch.lastScanMin / 60)}))}</p>`}
    <div class="acts">${it && it.status === "waiting" && h === 0 ? `<button class="btn primary sm" data-do="openItem" data-id="${it.id}"><span class="t">${t("node.go")}</span></button>` : ""}
      ${it ? `<button class="btn sm" data-do="story" data-id="${it.id}"><span class="t">${t("act.story")}</span></button>` : ""}
      <button class="btn sm ${F.focus ? "on" : ""}" data-do="wFocus" aria-pressed="${F.focus}"><span class="t">${t("world.focus")}</span><kbd>G</kbd></button>
      <button class="btn sm" data-do="wPathFrom"><span class="t">${t("path.from")}</span></button>
      <button class="btn sm quiet" data-do="wAsk"><span class="t">${t("act.ask")}</span><kbd>E</kbd></button></div>`;
  el.hidden = false;
}
function panels(keepTools){ if (!keepTools) renderTools(); else { renderHits(); const c = $(".wcount"); if (c) c.textContent = t("world.showing", {n: num(sc.shown), total: num(sc.totals.nodes - sc.gone.size)}); }
  renderHappen(); renderScrub(); renderLegend(); nodeCard(); }
function render(){
  const ready = S.view === "ready";
  if (S.want3d){ S.want3d = false; if (ready) setTimeout(() => setView("3d"), 0); }          // the address asked for the 3D view
  if (S.wantSel && ready){ const n = NF.sky.data.nodes.find(x => x.name === S.wantSel); S.wantSel = null;   // …or one resource (#/world/<name>)
    if (n){ Object.assign(F, {sel: n, focus: false, pathMode: false, a: null, b: null}); setTimeout(() => fly(n), 0); } else NF.notify(t("world.notFound")); }
  $("#wstate").hidden = ready; ["#wleft", "#legend", "#scrubCard"].forEach(s => { $(s).hidden = !ready; });
  NF.sky.view.blank = !ready; document.body.classList.toggle("view3d", ready && is3d()); NF.sky3.show(ready && is3d());
  if (!ready){
    $("#nodecard").hidden = true; $("#wpast").hidden = true; $("#whint").hidden = true; stop();
    $("#wstate").innerHTML = S.view === "empty" ? `<div class="state"><div class="big">${t("world.empty.big")}</div><p>${t("world.empty.p")}</p></div>` : NF.stateBlock(S.view, "world.failed.p");
    return;
  }
  compute(); panels(false);
}
/* the store, a filter or the hour changed: work the result out again and redraw — never the search box while someone types in it */
const refresh = () => { if (S.view !== "ready" || !$("#wstate").hidden) return render(); compute(); panels(document.activeElement && document.activeElement.id === "wq"); };

/* ── choosing ──────────────────────────────────────────────────────────── */
const fly = n => { if (is3d()) NF.sky3.flyTo(n); else NF.sky.flyTo(n); };
const home = () => { if (is3d()) NF.sky3.home(); else NF.sky.home(); };
function pick(n, flyTo = true){                     // a resource was chosen — on the map, in a list, by a search
  if (F.pathMode){
    if (!n) return;
    if (!F.a || F.b){ F.a = n; F.b = null; } else if (n !== F.a) F.b = n;
    refresh(); if (F.b && sc.path) home(); return;
  }
  F.sel = n; if (!n) F.focus = false; if (n && flyTo) fly(n); refresh();
}
function setTime(h){ S.hoursAgo = Math.max(0, Math.min(24, h)); refresh(); }
function stop(){ if (timer){ clearInterval(timer); timer = null; } F.playing = false; }
function play(){
  if (F.playing){ stop(); renderScrub(); return; }
  F.playing = true; if (S.hoursAgo === 0) S.hoursAgo = 24;                       // from a day ago up to now, in about 12 seconds
  timer = setInterval(() => { if (S.lens !== "world"){ stop(); return; } const h = Math.max(0, +(S.hoursAgo - .1).toFixed(2)); if (h === 0) stop(); setTime(h); }, 50);
  renderScrub();
}
function pathMode(on, from){ F.pathMode = on; F.focus = false; F.a = on ? (from || F.sel) : null; F.b = null; refresh(); }
function setView(v){
  if (v === F.view) return;
  const frame = () => { if (F.pathMode && sc && sc.path) home(); else if (F.sel && !F.pathMode) fly(F.sel); };   // the other view opens on the same thing
  if (v === "2d"){ F.view = "2d"; NF.syncHash(); render(); return frame(); }
  const tabs = $("#wtools .wview"); if (tabs) tabs.classList.add("busy");
  NF.sky3.load(ok => {                              // the 3D engine is fetched the first time it is asked for
    if (!ok){ NF.notify(t("view.failed")); return render(); }
    F.view = "3d"; NF.sky3.on({ pick: n => pick(n, !!n), hover, move: e => { const tip = $("#tip"); tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px"; }, changed: renderScrub });
    NF.syncHash(); if (S.lens === "world"){ render(); frame(); }
  });
}
function hover(n){ const tip = $("#tip"); if (!n){ tip.hidden = true; return; } tip.textContent = n.name + "　" + t("type." + n.type) + "　" + t("health." + W.health(n, S.hoursAgo, NF.store)); tip.hidden = false; }

Object.assign(NF.on, {
  openItem: el => { S.filter = "all"; S.cur = el.dataset.id; NF.setLens("decide"); },
  wNode: el => pick(NF.sky.data.nodes[+el.dataset.i]),
  wClose: () => { pick(null); home(); },
  wAbn: () => { F.onlyAbnormal = !F.onlyAbnormal; refresh(); },
  wEvent: el => { stop(); setTime(+el.dataset.h); },
  wStep: el => { stop(); setTime(W.stepEvent(NF.store.events, S.hoursAgo, +el.dataset.d)); },
  wPlay: () => play(),
  wNow: () => { stop(); setTime(0); },
  wAsk: () => { if (F.sel) NF.openChat({resource: F.sel.name, account: F.sel.account}); },       // a new conversation about this resource
  wView: el => setView(el.dataset.v),
  wFocus: () => { if (!F.sel) return; F.focus = !F.focus; refresh(); },
  wPath: () => pathMode(!F.pathMode),
  wPathFrom: () => pathMode(true, F.sel),
  wPathDemo: () => { const by = r => NF.sky.data.hot.find(h => h.ref === r).node; F.pathMode = true; F.focus = false; F.a = by("I12"); F.b = by("I8"); refresh(); home(); },
  wTurn: () => { NF.sky3.turn(!NF.sky3.turning); renderScrub(); },
  wHome: () => home(),
});

NF.screens.world = {
  render, refresh,
  get scene(){ return sc; }, check,
  leave(){ stop(); NF.sky3.show(false); document.body.classList.remove("view3d"); NF.sky.view.off = false; $("#tip").hidden = true; },
  key(e, k){
    if (S.view !== "ready") return;
    if (k === "f"){ e.preventDefault(); const q = $("#wq"); q.focus(); q.select(); return; }
    if (k === "v") return setView(F.view === "2d" ? "3d" : "2d");
    if (k === "p") return play();
    if (k === "[" || k === ","){ stop(); return setTime(W.stepEvent(NF.store.events, S.hoursAgo, -1)); }
    if (k === "]" || k === "."){ stop(); return setTime(W.stepEvent(NF.store.events, S.hoursAgo, 1)); }
    if (k === "0"){ stop(); return setTime(0); }
    if (k === "l") return pathMode(!F.pathMode);
    if (k === "g") return NF.on.wFocus();
    if (k === "h") return home();
    if (k === "r" && is3d()) return NF.on.wTurn();
    if (k === "e" && F.sel){ e.preventDefault(); return NF.on.wAsk(); }
  },
  /* Esc peels one layer at a time: the path, «only around it», the open resource, a moved camera. */
  esc(){ if (F.pathMode){ pathMode(false); return true; } if (F.focus){ F.focus = false; refresh(); return true; } if (F.sel){ NF.on.wClose(); return true; } home(); return false; },
  init(){
    const el = $("#world"), tip = $("#tip"); let drag = null;
    $("#scrub").addEventListener("input", e => { stop(); setTime((240 - +e.target.value) / 10); });
    el.addEventListener("input", e => { if (e.target.id === "wq"){ F.q = e.target.value; refresh(); } });
    el.addEventListener("change", e => { if (e.target.id === "wAcct"){ F.account = e.target.value; refresh(); } if (e.target.id === "wType"){ F.type = e.target.value; refresh(); } });
    el.addEventListener("keydown", e => { if (e.target.id === "wq" && e.key === "Enter" && sc.hits[0]){ const n = sc.hits[0]; e.target.blur(); pick(n); } });
    /* gestures on the flat map itself (the section, wherever no panel covers it); the 3D view has its own controls */
    el.addEventListener("pointerdown", e => { if (e.target !== el || S.view !== "ready" || is3d()) return; drag = {x: e.clientX, y: e.clientY, moved: false}; el.setPointerCapture(e.pointerId); });
    el.addEventListener("pointermove", e => {
      if (is3d()) return;
      if (drag){ const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (drag.moved || Math.hypot(dx, dy) > 4){ drag.moved = true; NF.sky.panBy(dx, dy); drag.x = e.clientX; drag.y = e.clientY; el.style.cursor = "grabbing"; tip.hidden = true; } return; }
      if (e.target !== el || S.view !== "ready"){ tip.hidden = true; el.style.cursor = ""; return; }
      const n = NF.sky.pick(e.clientX, e.clientY); el.style.cursor = n ? "pointer" : "grab"; hover(n);
      tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px";
    });
    el.addEventListener("pointerup", e => { const d = drag; drag = null; el.style.cursor = ""; if (!d || d.moved || is3d()) return; pick(NF.sky.pick(e.clientX, e.clientY) || null, false); });
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
    el.addEventListener("wheel", e => { if (e.target !== el || S.view !== "ready" || is3d()) return; e.preventDefault(); NF.sky.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * .0016)); }, {passive: false});
    setInterval(() => { if (S.lens === "world" && S.view === "ready") check(); }, 1000);          // and keep checking while the lens is open
  },
};
})();
