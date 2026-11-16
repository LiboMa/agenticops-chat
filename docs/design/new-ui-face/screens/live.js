/* new-UI-face — the «现场» lens: everything agents are doing right now, one lane each, and the one lane you opened.
   The rules are in model-live.js. A person can say a word to an agent that is still thinking, pause it, stop a run
   (hold: it rolls back), or take back a decision that is still inside its undo window. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, L = NF.live;
const GROUPS = ["running", "waiting", "finished"];
const lanes = () => S.view === "empty" ? [] : L.lanes(NF.store, NF.runs);
const sample = id => NF.runs.find(r => r.id === id);
const stale = () => S.view === "failed";               // the stream dropped: the last picture stays, nothing can be done to it
function current(){
  const ls = lanes(); if (!ls.length){ S.liveSel = null; return null; }
  return ls.find(l => l.id === S.liveSel) || (S.liveSel = ls[0].id, ls[0]);
}
/* the step strip: one mark per step — done, now, to come, held by you, never ran */
const strip = (l, big) => l.progress != null && l.state !== "done"
  ? `<div class="barp"><i style="width:${l.progress}%"></i></div>`
  : `<div class="strip${big ? " big" : ""}" aria-hidden="true">${l.steps.map(s => `<i class="${s.status}${s.you ? " you" : ""}"></i>`).join("")}${"<i class=\"todo\"></i>".repeat(Math.max(0, l.total - l.steps.length))}</div>`;
const stateCls = l => l.state === "paused" ? "held" : l.group === "waiting" ? "wait" : l.group === "finished" ? "done" : l.state === "stopping" || l.state === "rollback" ? "stop" : "run";

function renderLanes(){
  const ls = lanes(), cur = current(), el = $("#lanes");
  if (S.view === "loading"){ el.innerHTML = `<div class="rail-title"><span>${t("lens.live")}</span></div>` + `<div class="lane"><div class="skel" style="width:50%"></div><div class="skel" style="width:86%;margin-top:10px"></div></div>`.repeat(3); return; }
  el.innerHTML = `<div class="rail-title"><span>${t("live.title")}</span><span class="conn ${stale() ? "off" : ""}"><i></i>${t(stale() ? "live.offline" : "live.connected")}</span></div>
    ${stale() ? `<p class="stalebar" role="alert">${esc(t("live.stale", {t: NF.clockAt(S.lastOk)}))}　<button class="btn sm" data-do="retry"><span class="t">${t("state.retry")}</span></button></p>` : ""}`
    + GROUPS.map(g => { const part = ls.filter(l => l.group === g); return !part.length ? "" : `<h2 class="lgroup">${t("live.group." + g)}<span class="num">${part.length}</span></h2>`
      + part.map(l => `<button class="lane ${stateCls(l)}" data-do="lane" data-id="${l.id}" aria-selected="${cur && cur.id === l.id}">
          <span class="lt"><span class="ag">${t("by." + l.agent)}</span><span class="st">${esc(l.label)}</span></span>
          <span class="ti">${esc(l.title)}</span>${l.sub ? `<span class="sb">${esc(l.sub)}</span>` : ""}${strip(l)}</button>`).join(""); }).join("");
}
function mark(s){ return s.you ? `<b class="youtag">${t("who.you")}</b>` : s.find ? NF.prov(true) : s.act ? `<span class="actm" title="${t("live.kind.act")}">▸</span>` : NF.prov(false); }
function renderStream(){
  const el = $("#stream"), l = current(), may = NF.store.canDecide() && !stale();
  if (S.view === "loading"){ el.innerHTML = NF.stateBlock("loading"); return; }
  if (!l){ const last = NF.runs.find(r => r.state === "done"), next = NF.runs.find(r => r.stateKey === "live.scheduled");
    el.innerHTML = `<div class="state"><div class="big">${t("live.empty.big")}</div><p>${esc(t("live.empty.p", {last: last ? tx(last.title) : "—", next: next ? tx(next.title) + "　" + t(next.stateKey, next.stateVars) : "—"}))}</p></div>`; return; }
  const keepV = ($("#steerIn") || {}).value || "", hadFocus = document.activeElement && document.activeElement.id === "steerIn";
  const same = el.dataset.id === l.id, atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 48, keep = same && !atEnd ? el.scrollTop : null;   // follow the newest step unless the person scrolled up
  const it = l.itemId && NF.store.get(l.itemId), exec = l.agent === "executor";
  el.dataset.id = l.id;
  el.innerHTML = `<button class="back narrow-only" data-do="laneBack">← ${t("live.back")}</button>
    <div class="meta"><span class="ag">${t("by." + l.agent)}</span><span class="st ${stateCls(l)}">${esc(l.label)}</span>
      ${l.startedMin != null && l.group !== "finished" ? `<span>${esc(t("live.elapsed", {t: NF.fmtWait(l.startedMin)}))}</span>` : ""}
      ${it ? `<button class="story-link" data-do="story" data-id="${it.id}" style="margin-left:auto">${t("act.story")}<kbd>↵</kbd></button>` : ""}</div>
    <h1>${esc(l.title)}</h1>${l.sub ? `<p class="sub">${esc(l.sub)}</p>` : ""}
    ${strip(l, true)}
    <ol class="lsteps">${l.steps.map((s, k) => `<li class="${s.status}${s.you ? " you" : ""}"><span class="say">${mark(s)}${esc(tx(s.t))}${s.tier ? `<span class="tier ${s.tier === "write" ? "w" : ""}">${t("tier." + s.tier)}</span>` : ""}</span>
        ${s.cmd && !s.you ? `<code class="cmd">${esc(s.cmd)}</code>` : ""}</li>`).join("")}
      ${l.total > l.steps.length && l.state !== "done" ? `<li class="todo more">${esc(t("live.moreSteps", {n: l.total - l.steps.length}))}</li>` : ""}</ol>
    <p class="note">${NF.prov(true)}${t("prov.code")}　${NF.prov(false)}${t("prov.model")}　<span class="actm">▸</span> ${t("live.kind.act")}</p>
    <div class="controls" id="liveCtl">${!may ? (NF.store.canDecide() ? "" : `<span class="readonly-note">${t("readonly")}</span>`) : [
      l.can.steer ? `<form class="steer" data-form="steer"><input class="field" id="steerIn" placeholder="${t("live.steerPh")}" aria-label="${t("live.steerLabel")}" maxlength="200">
        <button class="btn" type="submit"><span class="t">${t("live.tell")}</span><kbd>E</kbd></button></form>` : "",
      l.can.pause ? `<button class="btn ${l.state === "paused" ? "primary" : ""}" id="primary" data-do="livePause"><span class="t">${t(l.state === "paused" ? "live.resume" : "live.pause")}</span><kbd>A</kbd></button>` : "",
      l.can.stop ? `<button class="btn danger" id="primary" data-hold="1"><span class="fill"></span><span class="t">${t("live.stop")}</span><kbd>A</kbd></button>` : "",
      l.can.undo ? `<button class="btn" data-do="undo"><span class="t">${t("live.undo")}</span><kbd>Z</kbd></button>` : "",
      exec && l.group === "running" ? `<span class="hintline">${t(l.state === "pending" ? "feed.canUndo" : l.state === "run" ? "live.noSteer" : l.state === "stopping" ? "live.stoppingNote" : "live.rollbackNote")}</span>` : "",
      it && it.status === "waiting" ? `<button class="btn" data-do="openItem" data-id="${it.id}"><span class="t">${t("node.go")}</span></button>` : "",
    ].join("")}</div>`;
  if (keep != null) el.scrollTop = keep; else el.scrollTop = el.scrollHeight;
  const inp = $("#steerIn"); if (inp){ inp.value = keepV; if (hadFocus) inp.focus(); }
}
function render(){ document.body.classList.toggle("lane-open", !!S.liveOpen); $("#live").classList.toggle("stale", stale()); renderLanes(); renderStream(); }

/* ── acting ────────────────────────────────────────────────────────────── */
let holdTimer = null;
function stopNow(){ const l = current(); if (!l || !l.can.stop) return; if (NF.store.stopRun(l.itemId)) NF.notify(t("toast.stopAsked", {ref: l.ref})); }
function holdStart(){
  const btn = $("#liveCtl #primary"); if (!btn || holdTimer) return;
  if (btn.dataset.hold !== "1"){ btn.click(); return; }
  btn.classList.add("holding"); holdTimer = setTimeout(() => { holdTimer = null; stopNow(); }, NF.HOLD_MS);
}
function holdEnd(){
  if (!holdTimer) return; clearTimeout(holdTimer); holdTimer = null;
  const btn = $("#liveCtl #primary"); if (!btn) return; btn.classList.remove("holding");
  const tx0 = btn.querySelector(".t"), old = tx0.textContent; tx0.textContent = t("act.holdHint"); setTimeout(() => { if (tx0.isConnected) tx0.textContent = old; }, 900);
}
function move(d){
  const ls = lanes(); if (!ls.length) return; const i = Math.max(0, ls.findIndex(l => l.id === S.liveSel));
  S.liveSel = ls[(i + d + ls.length) % ls.length].id; $("#stream").dataset.id = ""; render(); NF.syncHash();
  const sel = $('.lane[aria-selected="true"]'); if (sel) sel.scrollIntoView({block: "nearest"});
}
Object.assign(NF.on, {
  lane: el => { S.liveSel = el.dataset.id; S.liveOpen = true; $("#stream").dataset.id = ""; if (S.lens !== "live") NF.setLens("live"); else { render(); NF.syncHash(); } },
  laneBack: () => { S.liveOpen = false; render(); },
  livePause: () => { const l = current(), r = l && sample(l.id); if (r && L.pause(NF.store, r)) render(); },
});
NF.onSubmit.steer = form => {
  const l = current(), r = l && sample(l.id), i = form.querySelector("input");
  if (r && L.steer(NF.store, r, i.value)){ i.value = ""; $("#stream").dataset.id = ""; renderStream(); renderLanes(); NF.notify(t("live.told")); }
};
document.addEventListener("pointerdown", e => { if (S.lens !== "live") return; const b = e.target.closest && e.target.closest("#liveCtl #primary"); if (b && b.dataset.hold === "1") holdStart(); });
["pointerup", "pointercancel"].forEach(ev => document.addEventListener(ev, () => { if (S.lens === "live") holdEnd(); }, true));

NF.screens.live = {
  render, refresh: render,
  key(e, k){
    if (S.view === "loading") return;
    if (k === "j" || k === "arrowdown"){ e.preventDefault(); return move(1); }
    if (k === "k" || k === "arrowup"){ e.preventDefault(); return move(-1); }
    const l = current(); if (!l) return;
    if (k === "enter" && l.itemId){ e.preventDefault(); return NF.openStory(l.itemId); }
    if (stale() || !NF.store.canDecide()) return;
    if (k === "e" && l.can.steer){ e.preventDefault(); const i = $("#steerIn"); if (i) i.focus(); return; }
    if (k === "a" && !e.repeat && (l.can.pause || l.can.stop)) return holdStart();
  },
  keyup(e, k){ if (k === "a") holdEnd(); },
  init(){ setInterval(() => {                    // the sample background runs move on while the lens is open
    if (S.lens !== "live" || S.view !== "ready") return;
    if (L.tick(NF.runs)) render();
  }, 2600); },
};
})();
