/* new-UI-face — the command bar. A sentence asks the agent (in a new conversation); "/" lists commands, grouped, only those
   this person may use; anything else searches — issues, changes, plans, resources, reports, conversations, each with its
   state, so what no longer waits can be found again. "@" searches resources only. The rules are in model-chat.js. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, $$ = NF.$$, S = NF.S, t = (...a) => NF.t(...a), esc = NF.esc;
let sugg = [], sugIdx = 0;

/* the thing in front of the person, if any: the brief on «待决», the item on its «经过» page */
const curItem = () => S.lens === "decide" ? NF.current() : S.lens === "story" ? NF.store.get(S.story) : null;
function groups(v){
  if (!v || v.startsWith("/")){
    const q = v.replace(/^\//, "").trim().toLowerCase();
    return NF.chat.commands(S.role, curItem()).map(g => ({g: g.g, ref: g.ref, rows: g.rows
      .map(r => ({cmd: r.id, label: t(r.k, {ref: g.ref}), h: r.h}))
      .filter(r => !q || r.label.toLowerCase().includes(q) || (r.h || "").toLowerCase().includes(q))})).filter(g => g.rows.length);
  }
  const out = v.startsWith("@") ? [] : [{g: "ask", rows: [{ask: v, label: t(S.lens === "chat" ? "cmd.askNew" : "cmd.ask", {q: v}), h: t("cmd.enter")}]}];
  return out.concat(NF.chat.search(NF.store, NF.sky ? NF.sky.data.nodes : [], v, NF.chats.list).map(g => ({...g, rows: g.rows.map(r => ({...r, found: true}))})));
}
function row(r, k){
  const sel = `role="option" aria-selected="${k === sugIdx}" data-do="sugg" data-s="${k}"`;
  if (!r.found) return `<button ${sel}><span>${esc(r.label)}</span>${r.h ? `<kbd>${esc(r.h)}</kbd>` : ""}</button>`;
  const state = r.state ? `<small class="${r.open ? "" : "past"}">${t(r.state)}</small>` : r.gone ? `<small class="past">${t("health.gone")}</small>` : "";
  return `<button ${sel}>${r.ref ? `<span class="sref num">${esc(r.ref)}</span>` : ""}<span class="stitle">${esc(r.title)}</span>${state}</button>`;
}
function show(){
  const cmd = $("#cmd"), v = cmd.value.trim(), el = $("#sugg");
  const gs = groups(v); sugg = gs.flatMap(g => g.rows); sugIdx = Math.min(sugIdx, Math.max(0, sugg.length - 1));
  if (document.activeElement !== cmd){ el.hidden = true; return; }
  if (!sugg.length){ el.innerHTML = `<p class="snone">${t(v.startsWith("@") ? "search.noneAt" : "search.none")}</p>`; el.hidden = false; return; }
  let k = 0;
  el.innerHTML = gs.map(g => `<div class="sgh">${t("sgroup." + g.g, {ref: g.ref})}${g.more ? `<small>${t("search.more", {n: g.more})}</small>` : ""}</div>` + g.rows.map(r => row(r, k++)).join("")).join("");
  el.setAttribute("aria-label", t(v && !v.startsWith("/") ? "search.label" : "cmd.list"));
  el.hidden = false;
}
const notDrawn = stage => NF.notify(t("cmd.notDrawn", {stage}));
function runCommand(id){
  const it = curItem();
  if (id.startsWith("lens:")) return NF.setLens(id.slice(5));
  if (id.startsWith("draw:")) return notDrawn(id.slice(5));
  if (id.startsWith("slash:")){ const c = NF.chats.get(S.chatId); if (S.lens === "chat" && c) NF.chats.setDraft(c.id, id.slice(6) + " "); else NF.openChat({text: id.slice(6) + " "}); return NF.setLens("chat"); }
  switch (id){
    case "history": return NF.toggleHistory(true);
    case "critical": S.onlyCritical = true; S.filter = "all"; S.cur = null; S.curIdx = 0; NF.setLens("decide"); return NF.notify(t("cmd.criticalOn"));
    case "all": S.onlyCritical = false; S.filter = "all"; return NF.setLens("decide");
    case "theme": return NF.setTheme(S.theme === "night" ? "day" : "night");
    case "keys": return NF.openHelp();
    case "ask": return it && NF.openChat({ref: it.id});
    case "story": return it && NF.openStory(it.id);
    case "primary": case "close":                 // the decision itself is made on the brief, where its confirmation is
      if (!it) return; S.cur = it.id; S.filter = "all"; S.onlyCritical = false; NF.setLens("decide");
      return id === "close" ? NF.on.close() : setTimeout(() => { const b = $("#primary"); if (b) b.focus(); }, 0);
  }
}
function go(r){
  const g = r.go;
  if (g.item){ const it = NF.store.get(g.item); if (it.status === "waiting"){ S.filter = "all"; S.onlyCritical = false; S.cur = it.id; return NF.setLens("decide"); } return NF.openStory(it.id); }
  if (g.resource){ S.wantSel = g.resource; return NF.setLens("world"); }
  if (g.chat) return NF.openChat({id: g.chat});
  if (g.report) return notDrawn("D5");
}
function run(k){
  const r = sugg[k]; if (!r) return;
  $("#sugg").hidden = true; const cmd = $("#cmd"); cmd.value = ""; cmd.blur();
  if (r.ask) return NF.openChat({text: r.ask});            // a new conversation with the question written in, not sent
  if (r.found) return go(r);
  runCommand(r.cmd);
}
NF.on.sugg = el => run(+el.dataset.s);
NF.screens.command = { init(){
  const cmd = $("#cmd");
  cmd.addEventListener("input", () => { sugIdx = 0; show(); }); cmd.addEventListener("focus", () => { sugIdx = 0; show(); });
  cmd.addEventListener("blur", () => setTimeout(() => { $("#sugg").hidden = true; }, 120));
  cmd.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") e.stopPropagation();   // the bar's own keys: the screen behind must not act on them too
    if (e.key === "ArrowDown" || e.key === "ArrowUp"){ e.preventDefault(); if (!sugg.length) return;
      sugIdx = (sugIdx + (e.key === "ArrowDown" ? 1 : -1) + sugg.length) % sugg.length;
      $$("#sugg [role=option]").forEach((b, k) => b.setAttribute("aria-selected", k === sugIdx));
      const b = $$("#sugg [role=option]")[sugIdx]; if (b) b.scrollIntoView({block: "nearest"}); }
    else if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229){ e.preventDefault(); if (sugg.length) run(sugIdx); }
  });
} };
})();
