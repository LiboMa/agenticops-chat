/* new-UI-face — «对话»: the command bar's «问 agent» opened into a whole screen. Left: the conversations; right: one of
   them — what the agent did before it answered (the work log), the answer (text, a table, a chart, a flow), and the
   composer. The rules are in model-chat.js; the answers are canned sample text (zh). */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, $$ = NF.$$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc;
/* what each model reads of an attachment (chat/attachments/delivery.py, preamble.media_capabilities) */
const MODELS = [{id: "Opus 5.5", reads: "native"}, {id: "Sonnet 5.5", reads: "native"}, {id: "Fable 5.2", reads: "native"},
                {id: "GPT-6 Astra", reads: "images"}, {id: "gpt-oss-120b", reads: "text"}];
const EFFORTS = ["auto", "low", "standard", "high", "max"];
const SAMPLE_FILES = [
  {name: "grafana-0603.png", kind: "image", size: "412 KB"}, {name: "nginx-error.log", kind: "text", size: "64 KB"},
  {name: "runbook.pdf", kind: "pdf", size: "1.8 MB"}, {name: "report.pages", kind: "doc", size: "1.2 MB", refused: true},
];
let listFilter = "all";
const staged = {};                                  // per conversation: the files in its composer, kept with its draft

const cur = () => {                                 // the one open; else the most recent one; else none
  const c = NF.chats.get(S.chatId); if (c && (S.view !== "empty" || c.id.startsWith("n"))) return c;   // «no conversations yet» shows none of the sample ones
  const first = listed()[0]; if (first && S.view === "ready"){ S.chatId = first.id; return first; }
  return null;
};
const listed = () => {
  const all = NF.chats.ordered().filter(c => S.view !== "empty" || c.id.startsWith("n"));
  return listFilter === "ctx" ? all.filter(c => c.ctx) : listFilter === "pinned" ? all.filter(c => c.pinned) : all;
};
const acctName = id => { const a = NF.seed.accounts.find(x => x.id === id); return a ? tx(a.name) : id || ""; };
const when = h => h >= 24 ? t("ago.d", {n: Math.round(h / 24)}) : NF.clockAt(h) + " UTC";
const secs = ms => ms >= 1000 ? (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + " s" : ms + " ms";
/* what this model does with one file: native (reads the original), text (reads the extracted text), refused */
function delivery(f, model){
  if (f.refused || f.delivery === "refused") return "refused";
  if (f.delivery && !f.staged) return f.delivery;                       // a sent file says how it went
  const reads = (MODELS.find(m => m.id === model) || MODELS[0]).reads;
  if (f.kind === "text") return "text";
  if (f.kind === "image") return reads === "text" ? "text" : "native";
  return reads === "native" ? "native" : "text";
}

/* ── pieces ────────────────────────────────────────────────────────────── */
const mark = s => s.find ? NF.prov(true) : s.act ? `<span class="actm" title="${t("live.kind.act")}">▸</span>` : NF.prov(false);
function workLog(turn){
  const n = turn.work.length; if (!n && !turn.running) return "";
  const steps = turn.work.map((s, k) => {
    const now = turn.running && k === n - 1;
    const head = `${mark(s)}<span>${esc(tx(s.t))}</span>${s.ms && !now ? `<small class="num">${secs(s.ms)}</small>` : ""}`;   // a step still running has no duration yet
    const cmd = s.c ? `<code class="cmd mono">${esc(s.c)}</code>` : "";
    return `<li class="${now ? "now" : "done"}">${s.r ? `<details><summary>${head}</summary>${cmd}<pre class="mono res">${esc(tx(s.r))}</pre></details>` : `<div class="sh">${head}</div>${cmd}`}</li>`;
  }).join("");
  const legend = `<p class="note">${NF.prov(true)}${t("prov.code")}　${NF.prov(false)}${t("prov.model")}　<span class="actm">▸</span> ${t("live.kind.act")}</p>`;
  if (turn.running) return `<div class="work live" aria-live="polite"><div class="wh"><i class="dotlive"></i>${t("chat.work.running", {n: n || 1})}</div><ol class="lsteps">${steps}</ol>${legend}</div>`;
  const total = turn.secs != null ? turn.secs + " s" : secs(turn.work.reduce((a, s) => a + (s.ms || 0), 0));
  return `<details class="work"><summary>${t("chat.work.done", {n, t: total})}</summary><ol class="lsteps">${steps}</ol>${legend}</details>`;
}
/* refs in the answer open their «经过» page */
const linkRefs = s => esc(s).replace(/\b([IC])#(\d+)\b/g, (m, k, n) => `<button class="refl" data-do="chatRef" data-id="${k}${n}">${m}</button>`);
function table(tb){
  return `<div class="tscroll"><table class="grid"><thead><tr>${tb.head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${tb.rows.map(r => `<tr>${r.map(c => `<td>${linkRefs(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
/* One series, one colour (slot 1), columns ≤ 24 px with a 4 px rounded cap, square at the baseline; values on the caps in
   text ink; a hover title per column. The same numbers are in the table below it. */
function chart(ch, caption){
  const W = 360, H = 150, pad = {l: 8, r: 8, t: 22, b: 26}, s = ch.series[0], max = Math.max(...s.data, 1);
  const band = (W - pad.l - pad.r) / ch.x.length, bw = Math.min(24, band * .5), base = H - pad.b;
  const cols = s.data.map((v, i) => {
    const h = Math.max(2, (v / max) * (base - pad.t)), x = pad.l + band * i + (band - bw) / 2, y = base - h, r = Math.min(4, h);
    const path = `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${base}Z`;
    return `<g class="col"><title>${esc(ch.x[i])}：${v}</title><rect x="${pad.l + band * i}" y="${pad.t - 14}" width="${band}" height="${base - pad.t + 14}" fill="transparent"/>
      <path d="${path}"/><text class="v num" x="${x + bw / 2}" y="${y - 6}" text-anchor="middle">${v}</text>
      <text class="xl" x="${x + bw / 2}" y="${base + 17}" text-anchor="middle">${esc(ch.x[i])}</text></g>`;
  }).join("");
  return `<figure class="chart"><figcaption>${esc(caption || s.name)}</figcaption>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc((caption || s.name) + "：" + ch.x.map((x, i) => x + " " + s.data[i]).join("，"))}">
    <line class="base" x1="${pad.l}" x2="${W - pad.r}" y1="${base}" y2="${base}"/>${cols}</svg></figure>`;
}
/* a small flow: the first node on the left, what it touched in the middle, the rest on the right */
function flow(fl){
  const W = 420, rowH = 34, right = fl.nodes.length - 2, H = Math.max(3, right) * rowH + 12, bw = 104, bh = 26;
  const pos = fl.nodes.map((_, i) => i === 0 ? {x: 6, y: H / 2 - bh / 2} : i === 1 ? {x: 158, y: H / 2 - bh / 2} : {x: W - bw - 6, y: 6 + (i - 2) * rowH + (H - 12 - right * rowH) / 2 + 4});
  const edges = fl.edges.map(([a, b, l]) => { const A = pos[a], B = pos[b], x1 = A.x + bw, y1 = A.y + bh / 2, x2 = B.x, y2 = B.y + bh / 2, mx = (x1 + x2) / 2;
    return `<path class="e" d="M${x1},${y1}C${mx},${y1} ${mx},${y2} ${x2 - 6},${y2}" marker-end="url(#arr)"/>${l ? `<text class="el" x="${mx}" y="${Math.min(y1, y2) - 9}" text-anchor="middle">${esc(l)}</text>` : ""}`; }).join("");
  const nodes = fl.nodes.map((n, i) => `<g class="n"><rect x="${pos[i].x}" y="${pos[i].y}" width="${bw}" height="${bh}" rx="6"/><text x="${pos[i].x + bw / 2}" y="${pos[i].y + 17}" text-anchor="middle">${esc(n)}</text></g>`).join("");
  return `<figure class="flow"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(fl.edges.map(([a, b, l]) => fl.nodes[a] + " → " + fl.nodes[b] + (l ? "（" + l + "）" : "")).join("；"))}">
    <defs><marker id="arr" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L8,4L0,8Z" class="ah"/></marker></defs>${edges}${nodes}</svg></figure>`;
}
function fileCard(f, model, removable, k){
  const d = delivery(f, model), why = d === "refused" ? (f.why ? tx(f.why) : t("chat.file.refusedWhy")) : t("chat.file." + d);
  return `<div class="fcard ${d === "refused" ? "bad" : ""} k-${f.kind}" title="${esc(why)}">
    ${f.kind === "image" ? `<span class="thumb" aria-hidden="true"></span>` : `<span class="ficon" aria-hidden="true">${esc(t("chat.kind." + f.kind))}</span>`}
    <span class="fmeta"><b>${esc(f.name)}</b><small>${esc(f.size || "")}${f.size ? " · " : ""}${esc(why)}</small></span>
    ${removable ? `<button class="x" data-do="chatUnstage" data-k="${k}" aria-label="${t("chat.file.remove", {name: f.name})}">×</button>` : ""}</div>`;
}
function errorBlock(turn, last, c){
  const tip = turn.error === "timeout" ? t("chat.err.timeout.tip", {effort: t("effort." + c.effort)}) : t("chat.err.throttled.tip");
  return `<div class="cerr" role="alert"><b>${t("chat.err." + turn.error)}</b><p>${esc(tip)}</p>
    ${last ? `<button class="btn sm" data-do="chatRetry"><span class="t">${t("chat.retry")}</span></button>` : ""}</div>`;
}
function answer(turn, last, c){
  const a = turn.answer, may = NF.store.canDecide();
  const canRegen = last && !(turn.files && turn.files.length);              // the last answer only, never after a question with files
  return `<div class="ans">
    <p>${NF.prov(false)}${linkRefs(tx(a.text))}</p>
    ${a.chart ? chart(a.chart, a.chartTitle) : ""}${a.table ? table(a.table) : ""}${a.flow ? flow(a.flow) : ""}
    <div class="mact">
      <button class="btn sm quiet" data-do="chatCopy"><span class="t">${t("chat.copy")}</span></button>
      ${canRegen ? `<button class="btn sm quiet" data-do="chatRegen"><span class="t">${t("chat.regen")}</span></button>` : ""}
      ${may ? `<button class="btn sm quiet" data-do="chatSave"><span class="t">${t("chat.save")}</span></button>` : ""}
    </div></div>`;
}
function ctxBar(c){
  const locked = NF.chats.ctxLocked(c), busy = NF.chats.busy(c);
  const ctx = !c.ctx ? `<span class="ctx none">${t("chat.ctx.none")}</span>`
    : `<span class="ctx"><span class="ref">${esc(c.ctx.ref || c.ctx.resource)}</span><span>${esc(acctName(c.ctx.account))}</span>
        ${locked ? `<span class="lock">${t("chat.ctx.locked")}</span>` : `<button class="btn sm quiet" data-do="chatCtxOff"><span class="t">${t("chat.ctx.off")}</span></button>`}</span>`;
  const opt = (list, v, lab) => list.map(x => `<option value="${esc(x)}"${x === v ? " selected" : ""}>${esc(lab(x))}</option>`).join("");
  return `<header class="cbar">${ctx}
    <label class="sel"><span>${t("chat.model")}</span><select id="chatModel" ${busy ? "disabled" : ""}>${opt(MODELS.map(m => m.id), c.model, x => x)}</select></label>
    <label class="sel"><span>${t("chat.effort")}</span><select id="chatEffort" ${busy ? "disabled" : ""}>${opt(EFFORTS, c.effort, x => t("effort." + x))}</select></label></header>
    ${c.ctx && c.ctx.resource && !locked ? `<p class="cnote">${t("chat.ctx.resourceNew")}</p>` : ""}
    ${c.ctx && locked ? `<p class="cnote">${esc(t("chat.ctx.lockedNote", {acct: acctName(c.ctx.account)}))}</p>` : ""}
    ${!NF.store.canDecide() ? `<p class="cnote">${t("chat.readonly")}</p>` : ""}`;
}
function composer(c){
  const files = staged[c.id] || [], busy = NF.chats.busy(c), m = (MODELS.find(x => x.id === c.model) || MODELS[0]);
  return `<form class="composer" data-form="chat">
    ${files.length ? `<div class="tray">${files.map((f, k) => fileCard(f, c.model, true, k)).join("")}</div>` : ""}
    <div class="crow">
      <div class="attach"><button type="button" class="btn quiet" data-do="chatAttach" aria-haspopup="menu" aria-label="${t("chat.attach")}"><span class="t">＋</span></button>
        <div class="amenu" id="amenu" hidden role="menu">${SAMPLE_FILES.map((f, k) => `<button type="button" role="menuitem" data-do="chatAddFile" data-k="${k}">${esc(f.name)}<small>${esc(f.size)}</small></button>`).join("")}</div></div>
      <textarea id="chatIn" class="field" rows="1" placeholder="${t(c.turns.length ? "chat.ph.more" : "chat.ph")}" aria-label="${t("chat.label")}">${esc(NF.chats.draft(c.id))}</textarea>
      ${busy ? `<button type="button" class="btn danger" data-do="chatStop"><span class="t">${t("chat.stop")}</span></button>`
             : `<button type="submit" class="btn primary"><span class="t">${t("chat.send")}</span><kbd>↵</kbd></button>`}
    </div>
    <p class="mnote">${esc(t("chat.reads." + m.reads, {m: m.id}))}　${t("chat.keys")}</p></form>`;
}

/* ── the screen ────────────────────────────────────────────────────────── */
function renderList(){
  const el = $("#chatList"), c = cur();
  if (S.view === "loading"){ el.innerHTML = `<div class="rail-title"><span>${t("chat.list")}</span></div>` + `<div class="crow-item"><div class="skel" style="width:70%"></div><div class="skel" style="width:40%;margin-top:8px"></div></div>`.repeat(3); return; }
  const rows = S.view === "failed" ? [] : listed();
  el.innerHTML = `<div class="rail-title"><span>${t("chat.list")}</span><button class="btn sm" data-do="chatNew"><span class="t">${t("chat.new")}</span></button></div>
    <div class="pills">${["all", "ctx", "pinned"].map(f => `<button data-do="chatFilter" data-f="${f}" aria-pressed="${listFilter === f}">${t("chat.filter." + f)}</button>`).join("")}</div>
    <div class="clist" role="listbox" aria-label="${t("chat.list")}">${S.view === "failed" ? `<p class="note">${t("chat.list.failed")}</p>`
      : rows.length ? rows.map(x => `<button class="citem" role="option" data-do="chatOpen" data-id="${x.id}" aria-selected="${c && c.id === x.id}">
        <span class="r">${x.pinned ? `<b class="pin">${t("chat.pinned")}</b>` : ""}${x.ctx ? `<span class="id">${esc(x.ctx.ref || x.ctx.resource)}</span>` : ""}<span class="tm">${x.turns.length ? when(x.h) : t("chat.notSent")}</span></span>
        <span class="t">${esc(tx(x.title))}</span>${NF.chats.draft(x.id) ? `<span class="dr">${t("chat.draft")}</span>` : ""}${NF.chats.busy(x) ? `<span class="dr live">${t("chat.answering")}</span>` : ""}</button>`).join("")
      : `<p class="note">${t(S.view === "empty" ? "chat.list.empty" : "chat.list.none")}</p>`}</div>`;
}
function renderConvo(keepScroll){
  const el = $("#convo"), c = cur();
  if (S.view === "loading" || S.view === "failed"){ el.innerHTML = `<button class="back" data-do="chatBack">← ${t("chat.back." + (S.chatFrom || "decide"))}<kbd>Esc</kbd></button>` + NF.stateBlock(S.view, "chat.failed.p"); return; }
  if (!c){ S.chatId = NF.chats.open(NF.store).id; renderList(); return renderConvo(); }   // nothing to show: a new conversation, with a welcome
  const turns = $("#turns"), atEnd = !turns || turns.scrollHeight - turns.scrollTop - turns.clientHeight < 60, keep = turns && keepScroll && !atEnd ? turns.scrollTop : null;
  const focus = document.activeElement && document.activeElement.id === "chatIn";
  const last = c.turns.length - 1;
  el.innerHTML = `<button class="back" data-do="chatBack">← ${t("chat.back." + (S.chatFrom || "decide"))}<kbd>Esc</kbd></button>${ctxBar(c)}
    <div class="turns" id="turns">${!c.turns.length ? `<div class="welcome"><h1>${t(c.ctx ? "chat.welcome.ctx" : "chat.welcome")}</h1><p>${t(c.ctx ? "chat.welcome.ctxP" : "chat.welcome.p")}</p></div>` : ""}
    ${c.turns.map((tn, k) => `<div class="turn">
      <div class="you"><p>${esc(tn.q)}</p>${tn.files && tn.files.length ? `<div class="tray sent">${tn.files.map(f => fileCard(f, c.model, false)).join("")}</div>` : ""}</div>
      ${workLog(tn)}${tn.answer ? answer(tn, k === last, c) : ""}${tn.error ? errorBlock(tn, k === last, c) : ""}
      ${tn.stopped ? `<p class="note stopped">${t("chat.stopped")}</p>` : ""}
      ${k === last && tn.suggest && !tn.running ? `<div class="more" aria-label="${t("chat.next")}">${tn.suggest.map(s => `<button data-do="chatSugg">${esc(tx(s))}</button>`).join("")}</div>` : ""}</div>`).join("")}</div>
    ${composer(c)}`;
  /* opening a conversation shows its last question; while an answer streams, the view follows it unless the person scrolled up */
  const tl = $("#turns"), lt = tl.querySelector(".turn:last-child");
  if (keep != null) tl.scrollTop = keep;
  else if (!keepScroll && lt) tl.scrollTop += lt.getBoundingClientRect().top - tl.getBoundingClientRect().top - 8;
  else tl.scrollTop = tl.scrollHeight;
  grow(); if (focus) { const i = $("#chatIn"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
}
function render(){ renderList(); renderConvo(false); NF.syncHash(); }
function refresh(){ renderList(); renderConvo(true); }
const grow = () => { const i = $("#chatIn"); if (!i) return; i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 168) + "px"; };

/* Open a conversation — a new one about an item or a resource (its draft written, not sent), or one already had. */
NF.openChat = (opts = {}) => {
  if (opts.id && NF.chats.get(opts.id)) S.chatId = opts.id;
  else {
    const c = NF.chats.open(NF.store, opts);
    if (!opts.text && (opts.ref || opts.resource)) NF.chats.setDraft(c.id, opts.ref ? t("chat.draft.item", {ref: (NF.store.get(opts.ref) || {}).ref || opts.ref}) : t("chat.draft.resource", {name: opts.resource}));
    S.chatId = c.id;
  }
  NF.setLens("chat");
  setTimeout(() => { const i = $("#chatIn"); if (i){ i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 0);
};
function send(text){
  const c = cur(); if (!c) return;
  const files = (staged[c.id] || []).filter(f => delivery(f, c.model) !== "refused").map(f => ({...f, delivery: delivery(f, c.model), staged: false}));
  const refused = (staged[c.id] || []).filter(f => delivery(f, c.model) === "refused");
  if (!NF.chats.send(NF.store, c, text, files, refresh)) return;
  staged[c.id] = refused;                               // a refused file stays in the tray, with its reason, until removed
  render();
}
const saveDraft = () => { const c = cur(), i = $("#chatIn"); if (c && i) NF.chats.setDraft(c.id, i.value); };

Object.assign(NF.on, {
  chatOpen: el => { saveDraft(); S.chatId = el.dataset.id; render(); },
  chatNew: () => { saveDraft(); S.chatId = NF.chats.open(NF.store).id; render(); $("#chatIn").focus(); },
  chatFilter: el => { listFilter = el.dataset.f; renderList(); },
  chatBack: () => { saveDraft(); NF.setLens(S.chatFrom || "decide"); },
  chatCtxOff: () => { const c = cur(); if (c && NF.chats.clearCtx(c)) render(); },
  chatAttach: () => { const m = $("#amenu"); m.hidden = !m.hidden; if (!m.hidden) m.querySelector("button").focus(); },
  chatAddFile: el => { const c = cur(); (staged[c.id] = staged[c.id] || []).push({...SAMPLE_FILES[+el.dataset.k], staged: true}); saveDraft(); renderConvo(true); $("#chatIn").focus(); },
  chatUnstage: el => { const c = cur(); staged[c.id].splice(+el.dataset.k, 1); saveDraft(); renderConvo(true); },
  chatStop: () => { const c = cur(); if (c && NF.chats.stop(c)) refresh(); },
  chatRetry: () => { const c = cur(), tn = c && c.turns[c.turns.length - 1]; if (!tn) return; c.turns.pop(); NF.chats.send(NF.store, c, tn.q, tn.files, refresh, {retry: true}); render(); },
  chatRegen: () => { const c = cur(), tn = c && c.turns[c.turns.length - 1]; if (!tn) return; c.turns.pop(); NF.chats.send(NF.store, c, tn.q, [], refresh); render(); },
  chatSugg: el => { send(el.textContent); },
  chatCopy: () => NF.notify(t("chat.copied")),
  chatSave: () => NF.notify(t("cmd.notDrawn", {stage: "D5"})),
  chatRef: el => { const id = el.dataset.id, it = NF.store.get(id); if (!it) return NF.notify(t("chat.refMissing")); saveDraft(); if (it.status === "waiting"){ S.cur = id; S.filter = "all"; S.onlyCritical = false; NF.setLens("decide"); } else NF.openStory(id); },
});
NF.onSubmit.chat = form => { const i = form.querySelector("textarea"); send(i.value); };

NF.screens.chat = {
  render, refresh: () => { if (S.view === "ready") refresh(); else render(); },
  esc(){ const m = $("#amenu"); if (m && !m.hidden){ m.hidden = true; return; } NF.on.chatBack(); },
  key(e, k){ if (k === "enter"){ const i = $("#chatIn"); if (i){ e.preventDefault(); i.focus(); } } },
  init(){
    const el = $("#chat");
    el.addEventListener("input", e => { if (e.target.id === "chatIn"){ grow(); saveDraft(); renderListDraftMark(); } });
    el.addEventListener("change", e => { const c = cur(); if (!c) return; if (e.target.id === "chatModel"){ c.model = e.target.value; saveDraft(); renderConvo(true); } if (e.target.id === "chatEffort") c.effort = e.target.value; });
    el.addEventListener("keydown", e => {
      if (e.target.id !== "chatIn" || e.key !== "Enter") return;
      e.stopPropagation();
      if (e.shiftKey || e.isComposing || e.keyCode === 229) return;                 // a new line, or an input method still composing
      if (matchMedia("(pointer:coarse)").matches) return;                           // a touch keyboard's Enter is a new line; the button sends
      e.preventDefault(); if (!NF.chats.busy(cur())) send(e.target.value);
    });
    document.addEventListener("click", e => { const m = $("#amenu"); if (m && !m.hidden && !e.target.closest(".attach")) m.hidden = true; });
  },
};
/* the «草稿» mark in the list follows the composer without redrawing it */
function renderListDraftMark(){ const c = cur(); if (!c) return; const row = $(`.citem[data-id="${c.id}"]`); if (row && !!row.querySelector(".dr:not(.live)") !== !!NF.chats.draft(c.id)) renderList(); }
})();
