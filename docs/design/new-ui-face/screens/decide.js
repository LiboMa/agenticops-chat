/* new-UI-face — the «待决» lens: the queue, one brief at a time, and what agents are doing beside it. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc;

function renderQueue(){
  const c = NF.store.counts(), w = NF.shown(), cur = NF.current();
  $("#qTitle").textContent = t("queue.title");
  $("#qCount").textContent = S.view === "failed" ? "—" : S.view === "loading" ? "…" : S.view === "empty" ? 0 : c.all;
  $("#filters").innerHTML = ["all", ...NF.GROUPS].map(g =>
    `<button data-do="filter" data-g="${g}" aria-pressed="${S.filter === g}">${t("filter." + g)}${S.view === "ready" && g !== "all" && c[g] ? `<span class="n">${c[g]}</span>` : ""}</button>`).join("");
  const q = $("#queue"); q.setAttribute("aria-label", t("queue.label"));
  if (S.view === "loading"){ q.innerHTML = [0, 1, 2, 3].map(() => `<div class="skel" style="height:62px;border-radius:10px"></div>`).join(""); return; }
  if (S.view === "failed"){ q.innerHTML = ""; return; }
  q.innerHTML = w.map(i => `<button class="q ${i.tone}" role="option" aria-selected="${!!cur && i.id === cur.id}" data-do="pick" data-id="${i.id}">
    <span class="r"><span class="id">${i.ref}</span><span>${i.snoozed ? t("snoozed") : t("waited", {t: NF.fmtWait(i.waitMin)})}</span></span>
    <span class="t">${esc(tx(i.title))}</span><span class="need">${t("need." + i.reason)}</span></button>`).join("");
  $("#hint").innerHTML = `<kbd>J</kbd><kbd>K</kbd>${t("hint.move")} <kbd>${t("key.space")}</kbd>${t("hint.evidence")} <kbd>?</kbd>${t("hint.all")}`;
}

const briefKey = it => S.view === "loading" || S.view === "failed" ? "view:" + S.view
  : (it ? [it.id, it.rev, S.role, S.lang].join(":") : "none:" + S.lang);

function renderBrief(swap){
  const el = $("#brief"), it = NF.current(), w = NF.shown();
  S.rejecting = false; el.dataset.key = briefKey(it); el.setAttribute("aria-label", t("brief.label"));
  if (S.view === "loading" || S.view === "failed"){ el.innerHTML = NF.stateBlock(S.view); return; }
  if (!it){
    const working = NF.store.working().length + NF.runs.filter(r => r.state !== "done").length;
    el.innerHTML = `<div class="state"><div class="big">${t("clear.big")}</div><p>${t("clear.p")}</p>
      <div class="impact" style="justify-content:center;margin-top:22px"><div class="nums" style="gap:22px">
        <div><b style="color:var(--mint)">${NF.seed.watch.resources.toLocaleString("en-US")}</b>${t("clear.resources")}</div>
        <div><b style="color:var(--mint)">${NF.seed.watch.lastScanMin}</b>${t("clear.scan")}</div>
        <div><b style="color:var(--mint)">${working}</b>${t("clear.working")}</div></div></div>
      <p style="font-size:var(--fs-sm);margin-top:18px">${t("clear.honest")}</p></div>`;
    return;
  }
  const b = NF.briefs[it.kind], keep = swap ? 0 : el.scrollTop, acct = NF.seed.accounts.find(a => a.id === it.account);
  el.innerHTML = `<div class="meta"><span class="ref">${it.ref}</span><span class="sev ${it.tone}">${NF.sevLabel(it)}</span>
      <span>${it.snoozed ? t("snoozed") : t("waited", {t: NF.fmtWait(it.waitMin)})}</span><span>${acct ? esc(tx(acct.name)) : ""}　${it.region}</span>
      <span class="pos">${t("pos", {i: S.curIdx + 1, n: w.length})}</span><button class="story-link" data-do="story" data-id="${it.id}">${t("act.story")}<kbd>↵</kbd></button></div>
    <h1>${esc(tx(it.title))}</h1>
    ${it.returned ? `<p class="back">${t(it.returned)}</p>` : ""}
    <p class="ask"><b>${t("ask.lead")}</b>${esc(b.ask(it))}</p>
    ${b.body(it)}
    <div class="actions" id="actions">${NF.store.canDecide() ? b.buttons(it) : `<span class="readonly-note">${t("readonly")}</span>`}</div>`;
  el.scrollTop = keep;
  if (swap){ el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap"); }
}

function renderFeed(){
  $("#feedTitle").textContent = t("feed.title");
  const mine = NF.store.items.filter(i => i.run || i.agent).map(i => {
    if (i.agent) return `<div class="f run"><div class="h"><span><span class="dot"></span>${t("feed.agent")}</span><span class="num">${i.ref}</span></div><div>${t(i.agent.taskKey)}</div></div>`;
    if (!i.run) return "";
    const r = i.run, step = i.plan.steps[Math.min(r.step, r.total - 1)];
    return `<div class="f ${r.done ? "" : "run"}"><div class="h"><span><span class="dot"></span>${t(r.done ? "feed.done" : r.pending ? "feed.pending" : "feed.running")}</span><span class="num">${i.ref}</span></div>
      <div>${r.done ? NF.prov(true) + t("feed.checked", {n: i.checks.length}) : r.pending ? t("feed.canUndo") : esc(tx(step.say))}</div>
      <div class="barp"><i style="width:${r.done ? 100 : Math.round(r.step / r.total * 100)}%"></i></div></div>`;
  });
  const others = NF.runs.filter(r => r.state !== "done").map(r =>
    `<div class="f ${r.state === "run" ? "run" : ""}"><div class="h"><span><span class="dot" ${r.state === "wait" ? 'style="background:var(--amber)"' : ""}></span>${NF.runState(r)}</span></div><div>${esc(tx(r.title))}</div></div>`);
  $("#feed").innerHTML = mine.concat(others).join("");
}
NF.runState = r => r.stateKey ? t(r.stateKey, {n: r.agoMin}) : r.stateText;

/* ── evidence peek ─────────────────────────────────────────────────────── */
const evList = () => { const it = NF.current(); return it ? ((it.cause ? it.cause.ev : it.ev) || []) : []; };
function renderPeek(){
  const e = NF.seed.evidence[S.peek], list = evList(), el = $("#peek"); if (!e){ NF.closePeek(); return; }
  el.setAttribute("aria-label", t("peek.label"));
  el.innerHTML = `<h3><span class="num" style="color:var(--mint)">${S.peek}</span>　${esc(tx(e.title))}</h3><div class="src">${NF.prov(e.code)}${t("peek." + e.src)}</div><pre>${esc(tx(e.body))}</pre>
    <div class="nav"><span><kbd>←</kbd> <kbd>→</kbd> ${t("peek.next")}　<span class="num">${S.peekIdx + 1} / ${list.length}</span></span>
    <button class="btn sm" data-do="peekClose"><span class="t">${t("peek.close")}</span><kbd>Esc</kbd></button></div>`;
  el.hidden = false; document.body.classList.add("peeking");
}
NF.openPeek = id => { const list = evList(); S.peekIdx = Math.max(0, list.indexOf(id)); S.peek = list[S.peekIdx] || id; renderPeek(); };
NF.closePeek = () => { S.peek = null; $("#peek").hidden = true; document.body.classList.remove("peeking"); };
const peekStep = d => { const list = evList(); if (!list.length) return; S.peekIdx = (S.peekIdx + d + list.length) % list.length; S.peek = list[S.peekIdx]; renderPeek(); };

/* ── acting ────────────────────────────────────────────────────────────── */
let holdTimer = null;
const primary = () => { const it = NF.current(); if (!it) return; const b = NF.briefs[it.kind]; if (b.primary) b.primary(it); };
function holdStart(){
  const btn = $("#primary"); if (!btn || btn.disabled || holdTimer || S.rejecting) return;
  if (btn.dataset.hold !== "1"){ primary(); return; }
  btn.classList.add("holding"); holdTimer = setTimeout(() => { holdTimer = null; primary(); }, NF.HOLD_MS);
}
function holdEnd(){
  if (!holdTimer) return; clearTimeout(holdTimer); holdTimer = null;
  const btn = $("#primary"); if (!btn) return;
  btn.classList.remove("holding");
  const tx0 = btn.querySelector(".t"), old = tx0.textContent; tx0.textContent = t("act.holdHint");
  setTimeout(() => { if (tx0.isConnected) tx0.textContent = old; }, 900);
}
function move(d){
  const w = NF.shown(); if (!w.length) return;
  S.curIdx = (S.curIdx + d + w.length) % w.length; S.cur = w[S.curIdx].id;
  NF.closePeek(); renderQueue(); renderBrief(true); NF.sky && NF.sky.aim(); NF.syncHash();
  const sel = $('.q[aria-selected="true"]'); if (sel) sel.scrollIntoView({block: "nearest", inline: "nearest"});
}
/* One reason box, two ways to say no. mode "reject" = the brief's own «no» (ask for changes, fail an acceptance, withdraw…);
   mode "close" = close the item for good (dismiss an issue, reject a change). Enter sends the mode the box was opened in. */
function openReject(mode = "reject"){
  const it = NF.current(), b = it && NF.briefs[it.kind]; if (!it || !NF.store.canDecide()) return;
  const close = mode === "close";
  if (close ? !NF.canClose(it) : !b.reject) return;
  const change = it.entity === "change";
  const label = close ? (change ? "act.rejectChange" : "act.close")
    : b.rejectLabel || (change && it.kind === "accept" ? "act.failChange" : it.kind === "accept" ? "act.rejectAccept" : "act.reject");
  const ph = close ? (change ? "rejectChange.placeholder" : "close.placeholder") : b.rejectPlaceholder || (it.kind === "accept" ? "fail.placeholder" : "reject.placeholder");
  S.rejecting = true;
  $("#actions").innerHTML = `<form class="reason" data-form="reject" data-mode="${mode}"><input class="field" id="rejInput" placeholder="${t(ph)}" aria-label="${t(close ? "close.label" : "reject.label")}" maxlength="200">
    <button class="btn primary" type="submit"><span class="t">${t(label)}</span><kbd>↵</kbd></button>
    <button class="btn" type="button" data-do="rejectCancel"><span class="t">${t("act.cancel")}</span><kbd>Esc</kbd></button>
    ${close || b.rejectNote ? `<p class="note">${t(close ? (change ? "rejectChange.note" : "close.note") : b.rejectNote)}</p>` : ""}</form>`;
  $("#rejInput").focus();
}
NF.closeReject = () => renderBrief(false);
const ask = () => { const it = NF.current(), i = $("#cmd"); i.value = it ? `@${it.ref} ` : ""; i.focus(); };
const snooze = () => { const it = NF.current(); if (!it) return; const ref = it.ref; S.cur = null; if (NF.actions.snooze(NF.store, it.id)) NF.notify(t("toast.snoozed", {ref})); };

Object.assign(NF.on, {
  pick: el => { S.cur = el.dataset.id; NF.closePeek(); renderQueue(); renderBrief(true); NF.sky && NF.sky.aim(); NF.syncHash(); },
  filter: el => { S.filter = el.dataset.g; S.cur = null; S.curIdx = 0; NF.closePeek(); renderQueue(); renderBrief(true); NF.sky && NF.sky.aim(); NF.syncHash(); },
  peek: el => NF.openPeek(el.dataset.ev), peekClose: () => NF.closePeek(),
  tick: el => { const it = NF.current(); if (it) NF.actions.tick(NF.store, it.id, +el.dataset.k); },
  tickNext: () => { const it = NF.current(); if (it) NF.actions.tick(NF.store, it.id); },
  verdict: el => { const it = NF.current(); if (it) NF.actions.verdict(NF.store, it.id, el.dataset.v); },
  reject: () => openReject(), close: () => openReject("close"), rejectCancel: () => NF.closeReject(),
  ask: () => ask(), snooze: () => snooze(), primary: () => primary(),
  alt: el => { const it = NF.current(); if (it && NF.actions[el.dataset.a]) NF.actions[el.dataset.a](NF.store, it.id); },
  story: el => NF.openStory(el.dataset.id),
});
NF.onSubmit.reject = form => {
  const it = NF.current(), input = form.querySelector("input"); if (!it) return;
  const sent = form.dataset.mode === "close" ? NF.actions.close(NF.store, it.id, input.value) : NF.briefs[it.kind].reject(it, input.value);
  if (!sent){ input.value = ""; input.placeholder = t("reject.required"); input.focus(); }
};
document.addEventListener("pointerdown", e => { const b = e.target.closest && e.target.closest("#primary"); if (b && b.dataset.hold === "1") holdStart(); });
["pointerup", "pointercancel"].forEach(ev => document.addEventListener(ev, () => holdEnd(), true));

NF.screens.decide = {
  render(swap){ renderQueue(); renderBrief(swap); renderFeed(); },
  refresh(){                                    // the store changed: redraw the brief only if it is a different one
    renderQueue(); renderFeed();
    const el = $("#brief"), it = NF.current(), key = briefKey(it);
    if (el.dataset.key !== key) renderBrief(!(it && el.dataset.key.split(":")[0] === it.id));
    NF.syncHash();
  },
  key(e, k){
    if (S.peek){
      if (k === "arrowright") return peekStep(1);
      if (k === "arrowleft") return peekStep(-1);
      if (k === " "){ e.preventDefault(); return NF.closePeek(); }
    }
    const it = NF.current(); if (!it || S.view !== "ready") return;
    if (k === "j" || k === "arrowdown"){ e.preventDefault(); return move(1); }
    if (k === "k" || k === "arrowup"){ e.preventDefault(); return move(-1); }
    if (k === "a"){ if (!e.repeat) holdStart(); return; }
    if (k === "r"){ e.preventDefault(); return openReject(); }
    if (k === "d"){ e.preventDefault(); return openReject("close"); }
    if (k === "e"){ e.preventDefault(); return ask(); }
    if (k === "s") return snooze();
    if (k === " "){ e.preventDefault(); const l = evList(); if (l.length) NF.openPeek(l[0]); return; }
    if (k === "enter"){ e.preventDefault(); return NF.openStory(it.id); }
    const own = NF.briefs[it.kind].keys; if (own && own[k]) own[k](it);
  },
  keyup(e, k){ if (k === "a") holdEnd(); },
};
})();
