/* new-UI-face — the prototype's core: words, time, the store (logic, no DOM), then the shell.
   Classic script, one global (NF), so index.html opens by double-click. */
(function(){
"use strict";
const NF = window.NF = window.NF || {};
const $ = NF.$ = (s, el = document) => el.querySelector(s);
const $$ = NF.$$ = (s, el = document) => [...el.querySelectorAll(s)];
NF.esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
NF.HOLD_MS = 900;      // how long «approve» must be held
NF.UNDO_MS = 5000;     // the window in which a decision can be taken back
NF.STEP_MS = 1500;     // one step of a sample run
NF.AGENT_MS = 4000;    // sample agent work after a decision
NF.briefs = NF.briefs || {}; NF.actions = NF.actions || {}; NF.screens = NF.screens || {}; NF.on = NF.on || {}; NF.onSubmit = NF.onSubmit || {};

/* ── what the person is looking at ─────────────────────────────────────── */
const S = NF.S = { lens: "decide", cur: null, curIdx: 0, story: null, lang: "zh", theme: "night", role: "writer", view: "ready",
                   filter: "all", onlyCritical: false, peek: null, peekIdx: 0, hoursAgo: 0, rejecting: false, lastOk: 0.2 };

/* ── words and time ────────────────────────────────────────────────────── */
NF.t = (key, vars) => {
  let s = (NF.STR[S.lang] || NF.STR.zh)[key];
  if (s === undefined) s = NF.STR.zh[key];
  if (s === undefined) return key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "") : s;
};
NF.tx = v => (v && typeof v === "object" && "zh" in v) ? (v[S.lang] ?? v.zh) : v;
NF.pick = (v, lang) => (v && typeof v === "object" && "zh" in v) ? (v[lang] ?? v.zh) : v;      // a sample text in one given language
NF.clockAt = h => {                       // HH:MM (UTC) of «h hours before now»
  const m = NF.seed.nowMin - Math.round(h * 60), mm = ((m % 1440) + 1440) % 1440;
  return (m < 0 ? NF.t("time.yesterday") + " " : "") + String(Math.floor(mm / 60)).padStart(2, "0") + ":" + String(mm % 60).padStart(2, "0");
};
NF.fmtWait = min => min < 60 ? NF.t("unit.min", {n: min}) : min < 1440 ? NF.t("unit.hour", {n: Math.round(min / 60)}) : NF.t("unit.day", {n: Math.round(min / 1440)});
NF.sevLabel = it => it.severity ? NF.t("sev." + it.severity) : NF.t("sev.change") + (it.risk ? " " + it.risk : "");
NF.prov = code => `<span class="prov ${code ? "code" : "model"}" title="${NF.t(code ? "prov.code" : "prov.model")}"></span>`;
NF.eventText = e => e.key ? NF.t(e.key, e.vars) : NF.tx(e.t);

/* ── the store: every rule of the prototype lives here, with no DOM and an injected clock ── */
NF.realClock = { after(ms, fn){ const id = setTimeout(fn, ms); return () => clearTimeout(id); } };
NF.RANK = it => ({critical: 0, high: 1, medium: 2, low: 3}[it.severity] ?? ({L3: 1, L2: 2, L1: 3, L0: 3}[it.risk] ?? 4));
NF.GROUP_OF = { approval_required: "approval", verification_required: "acceptance", execution_failed: "failed",
                execution_not_started: "failed", review_required: "confirm", clarification_required: "confirm" };
NF.GROUPS = ["approval", "acceptance", "confirm", "failed"];

NF.createStore = function(seed, clock){
  const items = JSON.parse(JSON.stringify(seed.items)).map(i => Object.assign(i, {status: "waiting", rev: 0}));
  const past = JSON.parse(JSON.stringify(seed.past || [])).map(i => Object.assign(i, {rev: 0}));   // no longer waiting: found again by search, never in the queue
  const events = seed.events.map(e => ({...e}));
  const listeners = new Set();
  let pending = null, seq = 0;                 // the one decision still inside its undo window
  let runSeq = 47;                             // the sample data's runs end at #47
  const store = {
    items, past, events, role: "writer", notice(){},
    get: id => items.find(i => i.id === id) || past.find(i => i.id === id),
    all: () => items.concat(past),
    on(fn){ listeners.add(fn); return () => listeners.delete(fn); },
    emit(){ listeners.forEach(fn => fn()); },
    canDecide: () => store.role !== "viewer",
    /* The queue: the most severe first, then the longest wait. */
    waiting(filter){
      return items.filter(i => i.status === "waiting" && (!filter || filter === "all" || NF.GROUP_OF[i.reason] === filter))
                  .sort((a, b) => NF.RANK(a) - NF.RANK(b) || b.waitMin - a.waitMin);
    },
    counts(){
      const c = {all: 0}; NF.GROUPS.forEach(g => { c[g] = 0; });
      items.forEach(i => { if (i.status === "waiting"){ c.all++; c[NF.GROUP_OF[i.reason]]++; } });
      return c;
    },
    working: () => items.filter(i => (i.run && !i.run.done) || i.agent),
    pending: () => pending,
    /* Every decision goes through here. It shows at once, takes effect after UNDO_MS, and until then undo() takes
       it back. A new decision settles the one before it: only the last decision can be undone. */
    act(id, label, {apply, revert, commit}){
      store.settle();
      apply();
      const me = pending = {id, label, seq: ++seq, revert, commit, cancel: null};
      me.cancel = clock.after(NF.UNDO_MS, () => { if (pending === me){ pending = null; if (commit) commit(); store.emit(); } });
      store.emit();
      return me;
    },
    settle(){ if (!pending) return; const p = pending; pending = null; p.cancel(); if (p.commit) p.commit(); },
    undo(){ if (!pending) return false; const p = pending; pending = null; p.cancel(); p.revert(); store.emit(); return true; },
    log(k, key, vars){ events.push({h: 0.01, k, key, vars}); },
    /* A sample run: one step every STEP_MS; NF.afterRun says what the item becomes. */
    startRun(id){
      const it = store.get(id); if (!it || !it.run) return;
      it.run.pending = false; it.status = "running"; store.emit();
      const step = () => {
        if (!it.run || it.run.done) return;
        it.run.step++;                                           // the step that was running has finished
        if (it.run.step >= it.run.total){                        // …and it was the last one: a stop asked for during it came too late
          if (it.run.stopping){ delete it.run.stopping; store.notice("toast.stopTooLate", {ref: it.ref}); }
          it.run.done = true; NF.afterRun(store, it); store.emit(); return;
        }
        if (it.run.stopping){                                    // stop: no further step; the plan's rollback runs, then NF.afterStop
          it.run.rollingBack = true; store.emit();
          clock.after(NF.STEP_MS, () => { if (it.run && it.run.rollingBack){ NF.afterStop(store, it); store.emit(); } });
          return;
        }
        store.emit(); clock.after(NF.STEP_MS, step);
      };
      clock.after(NF.STEP_MS, step);
    },
    /* «叫停»: the step in progress finishes, nothing after it starts, the rollback runs. Inside the undo window, undo is the tool. */
    stopRun(id){
      const it = store.get(id);
      if (!it || !it.run || it.status !== "running" || it.run.done || it.run.stopping || it.run.rollingBack || !store.canDecide()) return false;
      it.run.stopping = true; store.emit(); return true;
    },
    newRunId: () => ++runSeq,
    /* Agent work that follows a decision: the item leaves the queue and shows under «agents at work». */
    agentWork(id, taskKey, then){
      const it = store.get(id); it.status = "agent"; it.agent = {taskKey}; store.emit();
      clock.after(NF.AGENT_MS, () => { delete it.agent; if (then) then(it); else it.status = "handed"; store.emit(); });
    },
  };
  return store;
};
NF.afterRun = (store, it) => {
  if (it.afterRun === "acceptance" && it.acceptAfter){       // a check has no result: the run comes back for acceptance
    const n = it.acceptAfter; delete it.acceptAfter; delete it.afterRun; delete it.run;
    Object.assign(it, n, {status: "waiting", waitMin: 0, snoozed: false, ticks: undefined, rev: it.rev + 1});
    store.log("decision", "event.back", {ref: it.ref}); store.notice("toast.back", {ref: it.ref});
    return;
  }
  it.status = "fixed";
  store.log("agent", "event.fixed", {ref: it.ref});
  store.notice("toast.done", {ref: it.ref, n: (it.checks || []).length});
};
/* An agent finished what a decision asked of it: the item comes back as its `next` situation, or stays handed. */
NF.comeBack = (store, it) => {
  if (!it.next){ it.status = "handed"; return; }
  const n = it.next; delete it.next; delete it.agentState;
  Object.assign(it, n, {status: "waiting", waitMin: 0, snoozed: false, ticks: undefined, rev: it.rev + 1});
  store.log("decision", "event.back", {ref: it.ref}); store.notice("toast.back", {ref: it.ref});
};

/* The backend's own state of an item (10 for an issue, 12 for a change), from what the prototype knows.
   Checked against models.py (_ISSUE_TRANSITIONS, CHANGE_TRANSITIONS) and services/work_phases.py.
   NF.STATES = who a state waits on when nothing else is known (the gallery's 22 lines); NF.waitsOn(it) is the answer for one item. */
NF.STATES = {
  issue: {open: "agent", investigating: "agent", acknowledged: "agent", root_cause_identified: "you", fix_planned: "you", fix_approved: "executor",
          fix_executing: "agent", fix_executed: "you", resolved: "none", dismissed: "none"},
  change: {draft: "you", under_review: "agent", needs_clarification: "you", planned: "you", approved: "executor", executing: "agent",
           needs_review: "you", completed: "none", failed: "none", rolled_back: "none", rejected: "none", cancelled: "none"},
};
NF.STATE_OF = {
  issue: {needsNewPlan: "root_cause_identified", planRejected: "fix_planned", needsReview: "root_cause_identified", rcaRejected: "root_cause_identified",
          toGenerate: "root_cause_identified", awaitingApproval: "fix_planned", notQueued: "fix_approved", awaitingAcceptance: "fix_executed",
          passed: "fix_executed", unverified: "fix_executed"},
  change: {draft: "draft", needsClarification: "needs_clarification", awaitingApproval: "planned", notQueued: "approved", awaitingAcceptance: "needs_review"},
};
NF.stateOf = it => {
  const issue = it.entity === "issue";
  switch (it.status){
    case "waiting": return NF.STATE_OF[it.entity][it.situation];
    case "pending": return issue ? "fix_approved" : "approved";
    case "running": return issue ? "fix_executing" : "executing";
    case "fixed": case "done": return it.endState || (issue ? "resolved" : "completed");
    case "withdrawn": return issue ? "root_cause_identified" : "cancelled";   // an approval taken back before the run began
    case "cancelled": return "cancelled";
    case "closed": return issue ? "dismissed" : "rejected";
    default: return it.agentState || (issue ? "investigating" : "under_review");      // sent / agent / handed
  }
};
/* the state an item is in while an agent does what a decision asked for */
NF.AGENT_STATE = {
  "agent.replanning": {issue: "fix_planned", change: "under_review"},    // the plan was sent back; the next version is being written
  "agent.planning": {issue: "root_cause_identified"},
  "agent.rediagnose": {issue: "investigating"},
  "agent.rechecking": {issue: "fix_executed"},
  "agent.reviewing": {change: "under_review"},
};
/* who this item waits on right now: you | agent | executor | none */
NF.waitsOn = it => ({waiting: "you", pending: "executor", running: "agent", sent: "agent", agent: "agent", handed: "agent"})[it.status] || "none";

/* ── the shell ─────────────────────────────────────────────────────────── */
NF.shown = () => S.view === "empty" ? [] : NF.store.waiting(S.filter).filter(i => !S.onlyCritical || i.severity === "critical");   // what the queue shows
NF.current = () => {
  const w = NF.shown(); if (!w.length){ S.cur = null; return null; }
  let i = w.findIndex(x => x.id === S.cur);
  if (i < 0) i = Math.min(S.curIdx, w.length - 1);
  S.curIdx = i; S.cur = w[i].id; return w[i];
};

NF.pulseX = h => (1 - Math.sqrt(Math.min(h, 24) / 24)) * 100;    // recent hours get more room; the hour marks keep it honest
NF.renderTop = () => {
  const c = NF.store.counts(), n = S.view === "failed" ? "—" : S.view === "loading" ? "…" : S.view === "empty" ? 0 : c.all;
  const running = S.view !== "ready" || !NF.live ? "" : NF.live.lanes(NF.store, NF.runs).filter(l => l.group === "running").length;   // how many things agents are doing now
  const from = S.lens === "story" ? (S.storyFrom || "decide") : S.lens;
  $("#lens").innerHTML = ["decide", "live", "world", "chat"].map((l, i) =>
    `<button role="tab" data-do="lens" data-lens="${l}" aria-selected="${from === l}"><span class="n">${i + 1}</span>${NF.t("lens." + l)}${l === "decide" ? `<b class="cnt num">${n}</b>` : l === "live" && running ? `<b class="cnt run num">${running}</b>` : ""}</button>`).join("");
  $("#pulse").innerHTML = `<span class="lbl">${NF.t("pulse.label")}</span>`
    + [12, 6, 3, 1].map(h => `<span class="hm" style="left:${NF.pulseX(h)}%">${h}h</span>`).join("")
    + NF.store.events.map(e => `<i class="tick ${e.k}" style="left:${NF.pulseX(e.h)}%" data-tip="${NF.clockAt(e.h)}　${NF.esc(NF.eventText(e))}"></i>`).join("")
    + `<span class="now" title="${NF.t("pulse.now", {t: NF.clockAt(0)})}"></span>`;
  $("#pulse").setAttribute("aria-label", NF.t("pulse.label"));
  const unseen = NF.history ? NF.history.unseen() : 0;
  $("#who").innerHTML = `<button class="chip-btn scope" data-do="scope">${NF.t("scope.all")}</button>`
    + `<button class="chip-btn bell" data-do="history" aria-expanded="${!!$("#hist") && !$("#hist").hidden}" aria-label="${NF.t(unseen ? "hist.openN" : "hist.open", {n: unseen})}"><span class="wide">${NF.t("hist.short")}</span><svg class="ico narrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.2a4 4 0 0 0-4 4v2.6L2.8 11h10.4L12 8.8V6.2a4 4 0 0 0-4-4ZM6.5 12.6a1.6 1.6 0 0 0 3 0"/></svg>${unseen ? `<b class="num">${unseen}</b>` : ""}</button>`
    + `<button class="chip-btn" data-do="theme" aria-label="${NF.t("theme.toggle")}"><span class="wide">${NF.t("theme." + S.theme)}</span><span class="narrow" aria-hidden="true">◐</span></button>`
    + `<button class="chip-btn" data-do="help" aria-label="${NF.t("keys.open")}">?</button>`
    + `<button class="avatar" aria-label="${NF.t("account")}">${NF.seed.user.initials}</button>`;
  if ($("#hist")) $("#hist").setAttribute("aria-label", NF.t("hist.title"));
  if ($("#convo")) $("#convo").setAttribute("aria-label", NF.t("lens.chat"));
  $("#cmd").placeholder = NF.t("cmd.placeholder"); $("#cmd").setAttribute("aria-label", NF.t("cmd.label"));
  document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
};

/* The four states of a data module, drawn one way everywhere. */
NF.stateBlock = (view, failKey = "state.failed.p") => view === "loading"         // failKey: what a failure does NOT mean on this screen
  ? `<div class="state" role="status" aria-busy="true"><div class="skel" style="width:60%;height:22px"></div><div class="skel" style="width:86%;margin-top:14px"></div><div class="skel" style="width:74%;margin-top:8px"></div><p>${NF.t("state.loading")}</p></div>`
  : `<div class="state failed" role="alert"><div class="big">${NF.t("state.failed")}</div><p>${NF.t(failKey, {t: NF.clockAt(S.lastOk)})}</p><p><button class="btn" data-do="retry"><span class="t">${NF.t("state.retry")}</span></button></p></div>`;

NF.setLens = l => {
  /* where Esc goes back to: the lens it came from — a story too, unless that story was itself opened from the chat (no ping-pong) */
  if (l === "chat" && S.lens !== "chat" && !(S.lens === "story" && S.storyFrom === "chat")) S.chatFrom = S.lens;
  S.lens = l; NF.closePeek && NF.closePeek();
  ["decide", "live", "world", "story", "chat"].forEach(x => { $("#" + x).hidden = x !== l; });
  document.body.classList.toggle("in-chat", l === "chat");
  if (l !== "world"){ S.hoursAgo = 0; if (NF.screens.world && NF.screens.world.leave) NF.screens.world.leave(); }
  NF.render(true);
};
NF.render = swap => {
  NF.renderTop();
  const scr = NF.screens[S.lens]; if (scr) scr.render(swap);
  NF.sky && NF.sky.aim();
  NF.syncHash();
};
NF.syncHash = () => {
  const W = S.world || {};
  const h = S.lens === "story" ? "#/story/" + S.story : S.lens === "decide" && S.cur ? "#/decide/" + S.cur : S.lens === "live" && S.liveSel ? "#/live/" + S.liveSel
    : S.lens === "world" && W.sel && !W.pathMode ? "#/world/" + W.sel.name : S.lens === "world" && W.view === "3d" ? "#/world/3d"
    : S.lens === "chat" && S.chatId ? "#/chat/" + S.chatId : "#/" + S.lens;
  if (location.hash !== h) history.replaceState(null, "", h);
};
NF.readHash = () => {
  const m = /^#\/(decide|live|world|story|chat)(?:\/([\w-]+))?$/.exec(location.hash); if (!m) return;
  const it = m[2] && NF.store.get(m[2]);
  if (m[1] === "story"){ if (it){ S.lens = "story"; S.story = it.id; } return; }
  S.lens = m[1]; if (m[1] === "live"){ if (m[2]){ S.liveSel = m[2]; S.liveOpen = true; } return; }
  if (m[1] === "world"){ S.want3d = m[2] === "3d"; S.wantSel = m[2] && m[2] !== "3d" ? m[2] : null; return; }   // #/world/<resource name> opens on it
  if (m[1] === "chat"){ S.chatId = m[2] && NF.chats && NF.chats.get(m[2]) ? m[2] : null; return; }
  if (it) S.cur = it.id;
};

/* notices: a decision's undo line, or a plain line — both speak from the command bar's place */
let shownSeq = 0, noticeTimer = null;
const labelOf = l => typeof l === "string" ? l : NF.t(l.key, l.vars);
NF.syncToast = () => {
  const p = NF.store.pending(), el = $("#toast");
  if (p){
    if (p.seq === shownSeq) return;
    shownSeq = p.seq; clearTimeout(noticeTimer); noticeTimer = null;
    NF.remember({label: p.label, go: p.id, kind: "decision"});
    el.className = "toast"; void el.offsetWidth; el.className = "toast count";
    el.innerHTML = `<span class="spark" aria-hidden="true"></span><span class="msg">${NF.esc(labelOf(p.label))}</span><button data-do="undo">${NF.t("undo")}<kbd>Z</kbd></button><i class="cd"></i>`;
    el.hidden = false;
  } else if (shownSeq){ shownSeq = 0; if (!noticeTimer) el.hidden = true; }
};
/* the notice history: what the toasts said, kept after they are gone (newest first) */
NF.remember = entry => { if (!NF.history) return; NF.history.push(entry); NF.renderTop(); if (!$("#hist").hidden) NF.renderHistory(); };
NF.renderHistory = () => {
  const rows = NF.history.list();
  $("#hist").innerHTML = `<div class="hhead"><h2>${NF.t("hist.title")}</h2><button class="btn sm quiet" data-do="history"><span class="t">${NF.t("hist.close")}</span><kbd>Esc</kbd></button></div>
    <p class="note">${NF.t("hist.p")}</p>
    ${rows.length ? `<ol class="hlist">${rows.map(r => { const it = r.go && NF.store.get(r.go);
      return `<li class="${r.kind || "notice"}"><time class="num">${NF.clockAt(r.h)} UTC</time><span>${r.kind === "undo" ? `<b>${NF.t("hist.undone")}</b>` : r.kind === "decision" ? `<b>${NF.t("hist.you")}</b>` : ""}${NF.esc(r.key ? NF.t(r.key, r.vars) : labelOf(r.label))}</span>
        ${it ? `<button class="btn sm quiet" data-do="histGo" data-go="${it.id}"><span class="t">${NF.t("hist.go", {ref: it.ref})}</span></button>` : ""}</li>`; }).join("")}</ol>`
      : `<p class="note">${NF.t("hist.none")}</p>`}`;
};
NF.toggleHistory = open => {
  const el = $("#hist"); el.hidden = open === undefined ? !el.hidden : !open;
  if (!el.hidden){ NF.history.seen(); NF.renderHistory(); el.querySelector("button").focus(); }
  NF.renderTop();
};
NF.notify = text => {
  if (NF.store.pending()) return;                      // a plain line never covers an undo window
  const el = $("#toast"); clearTimeout(noticeTimer);
  el.className = "toast"; el.innerHTML = `<span class="spark" aria-hidden="true"></span><span class="msg">${NF.esc(text)}</span>`; el.hidden = false;
  noticeTimer = setTimeout(() => { noticeTimer = null; el.hidden = true; }, 2600);
};
NF.undo = () => {                                 // what was taken back comes back into view
  const p = NF.store.pending(); if (!p) return;
  S.cur = p.id; NF.store.undo(); NF.notify(NF.t("toast.undone"));
  NF.remember({label: p.label, go: p.id, kind: "undo"});
};

NF.setTheme = th => { S.theme = th; document.body.dataset.theme = th; NF.sky && NF.sky.recolor(); NF.renderTop(); };
NF.openHelp = () => {
  const K = (...ks) => ks.map(k => `<kbd>${k}</kbd>`).join("");
  const rows = [[K("J", "K"), "help.move"], [K("A"), "help.primary"], [K("R"), "help.reject"], [K("D"), "help.close"], [K("E"), "help.ask"], [K("S"), "help.snooze"],
                [K(NF.t("key.space")), "help.peek"], [K("X"), "help.tick"], [K("Y", "P", "N", "M"), "help.verdict"], [K("1", "2", "3", "4"), "help.lens"],
                [K("/"), "help.cmd"], [K("Z"), "help.undo"], [K("T"), "help.theme"],
                [K("E", "A"), "help.live"], [K("↵"), "help.chat"], [K("F", "P", "[", "]", "0"), "help.world"], [K("V", "G", "L", "H"), "help.world2"]];
  $("#help").innerHTML = `<div class="dialog" role="dialog" aria-modal="true" aria-label="${NF.t("keys.open")}"><h2>${NF.t("help.title")}</h2><p>${NF.t("help.p")}</p>
    <div class="keys">${rows.map(r => `<div>${r[0]}<span>${NF.t(r[1])}</span></div>`).join("")}</div>
    <p style="margin-top:14px">${NF.prov(true)}${NF.t("prov.code")}　${NF.prov(false)}${NF.t("prov.model")}。${NF.t("help.prov")}</p>
    <div style="text-align:right"><button class="btn" data-do="helpClose"><span class="t">${NF.t("help.ok")}</span><kbd>Esc</kbd></button></div></div>`;
  $("#help").hidden = false; $("#help button").focus();
};

/* the prototype's own switches (not part of the product) */
NF.renderDev = () => {
  const row = (k, title, opts, cur) => `<div class="row"><b>${NF.t(title)}</b><div class="pills">${opts.map(o =>
    `<button data-do="dev" data-k="${k}" data-v="${o[0]}" aria-pressed="${cur === o[0]}">${NF.t(o[1])}</button>`).join("")}</div></div>`;
  $("#devpop").innerHTML = `<span>${NF.t("dev.note")}</span>`
    + row("view", "dev.data", [["ready", "dev.ready"], ["loading", "dev.loading"], ["failed", "dev.failed"], ["empty", "dev.empty"]], S.view)
    + row("role", "dev.role", [["admin", "role.admin"], ["writer", "role.writer"], ["viewer", "role.viewer"]], S.role)
    + `<div class="row"><b>${NF.t("dev.lang")}</b><div class="pills"><button data-do="dev" data-k="lang" data-v="zh" aria-pressed="${S.lang === "zh"}">中文</button><button data-do="dev" data-k="lang" data-v="en" aria-pressed="${S.lang === "en"}">English</button></div><span>${NF.t("dev.langNote")}</span></div>`
    + row("theme", "dev.theme", [["night", "theme.night"], ["day", "theme.day"]], S.theme)
    + `<div class="row"><b>${NF.t("dev.map")}</b><div class="pills">${[0, 1900, 5000].map(c => `<button data-do="devMap" data-v="${c}" aria-pressed="${(S.mapSize || 0) === c}">${(c || NF.seed.watch.resources).toLocaleString("en-US")}</button>`).join("")}</div><span id="devFps">${NF.t("dev.fps", {n: NF.sky ? NF.sky.fps : 0, ms: NF.sky ? NF.sky.drawMs.toFixed(1) : 0})}</span></div>`
    + `<button class="btn sm" data-do="devReset"><span class="t">${NF.t("dev.reset")}</span></button>`;
  $("#devbtn").textContent = NF.t("dev.title");
};

NF.boot = () => {
  NF.store = NF.createStore(NF.seed, NF.realClock);
  NF.store.role = S.role;
  NF.store.notice = (key, vars) => { NF.remember({key, vars, go: vars && vars.ref ? vars.ref.replace("#", "") : null}); NF.notify(NF.t(key, vars)); };
  NF.chats = NF.chat ? NF.chat.createChats(NF.seed, NF.realClock) : null;
  NF.history = NF.chat ? NF.chat.createHistory(NF.seed.notices) : null;
  NF.store.on(() => { NF.syncToast(); NF.renderTop(); const scr = NF.screens[S.lens]; if (scr && scr.refresh) scr.refresh(); NF.sky && NF.sky.aim(); });
  NF.runs = JSON.parse(JSON.stringify(NF.seed.runs));
};

Object.assign(NF.on, {
  lens: el => NF.setLens(el.dataset.lens),
  theme: () => NF.setTheme(S.theme === "night" ? "day" : "night"),
  help: () => NF.openHelp(), helpClose: () => { $("#help").hidden = true; },
  history: () => NF.toggleHistory(),
  histGo: el => { const it = NF.store.get(el.dataset.go); NF.toggleHistory(false); if (!it) return;
    if (it.status === "waiting"){ S.cur = it.id; S.filter = "all"; S.onlyCritical = false; NF.setLens("decide"); } else NF.openStory(it.id); },
  scope: () => NF.notify(NF.t("scope.only")),
  undo: () => NF.undo(),
  retry: () => { S.view = "ready"; NF.renderDev(); NF.render(true); },
  devToggle: () => { const p = $("#devpop"); p.hidden = !p.hidden; if (!p.hidden) NF.renderDev(); },
  dev: el => {
    const {k, v} = el.dataset;
    if (k === "theme") NF.setTheme(v); else S[k] = v;
    if (k === "role") NF.store.role = v;
    NF.renderDev(); NF.render(true);
  },
  devMap: el => { S.mapSize = +el.dataset.v; NF.sky.rebuild(S.mapSize); if (S.world) Object.assign(S.world, {sel: null, focus: false, pathMode: false, a: null, b: null}); NF.renderDev(); NF.render(true); },
  devReset: () => {
    NF.boot(); S.chatId = null; S.cur = null; S.curIdx = 0; S.filter = "all"; S.onlyCritical = false; S.view = "ready"; S.hoursAgo = 0; S.liveSel = null; S.liveOpen = false; S.mapSize = 0;
    if (S.world) Object.assign(S.world, {q: "", account: "", type: "", onlyAbnormal: false, sel: null, focus: false, pathMode: false, a: null, b: null, playing: false});
    NF.sky.rebuild(); $("#toast").hidden = true; NF.renderDev(); NF.render(true);
  },
});

NF.start = () => {
  NF.boot(); NF.readHash();
  document.body.dataset.theme = S.theme;
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-do]"); if (!el) return;
    const fn = NF.on[el.dataset.do]; if (fn) fn(el, e);
  });
  document.addEventListener("submit", e => { e.preventDefault(); const fn = NF.onSubmit[e.target.dataset.form]; if (fn) fn(e.target, e); });
  document.addEventListener("keydown", e => {
    const inField = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName), cmd = $("#cmd");
    if (e.key === "Escape"){
      if (!$("#help").hidden){ $("#help").hidden = true; return; }
      if (!$("#devpop").hidden){ $("#devpop").hidden = true; return; }
      if (!$("#hist").hidden){ NF.toggleHistory(false); return; }
      if (S.peek){ NF.closePeek(); return; }
      if (S.rejecting){ NF.closeReject(); return; }
      if (inField){ document.activeElement.blur(); return; }
      if (S.lens === "story") NF.on.storyBack();
      else if (S.lens === "world") NF.screens.world.esc();
      else if (S.lens === "live" && S.liveOpen) NF.on.laneBack();
      else if (S.lens === "chat") NF.screens.chat.esc();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k"){ e.preventDefault(); cmd.focus(); return; }
    if (inField || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "/"){ e.preventDefault(); $("#toast").hidden = true; cmd.focus(); return; }
    if (k === "?"){ NF.openHelp(); return; }
    if (!$("#help").hidden) return;
    if (k === "1") return NF.setLens("decide");
    if (k === "2") return NF.setLens("live");
    if (k === "3") return NF.setLens("world");
    if (k === "4") return NF.setLens("chat");
    if (k === "t") return NF.setTheme(S.theme === "night" ? "day" : "night");
    if (k === "z") return NF.undo();
    const scr = NF.screens[S.lens]; if (scr && scr.key) scr.key(e, k);
  });
  document.addEventListener("keyup", e => { const scr = NF.screens[S.lens]; if (scr && scr.keyup) scr.keyup(e, e.key.toLowerCase()); });
  window.addEventListener("hashchange", () => { NF.readHash(); NF.setLens(S.lens); });
  NF.sky && NF.sky.init($("#sky"));
  NF.screens.command && NF.screens.command.init();
  NF.screens.world && NF.screens.world.init && NF.screens.world.init();
  NF.screens.live && NF.screens.live.init && NF.screens.live.init();
  NF.screens.chat && NF.screens.chat.init();
  NF.renderDev();
  setInterval(() => { const f = $("#devFps"); if (f && !$("#devpop").hidden) f.textContent = NF.t("dev.fps", {n: NF.sky.fps, ms: NF.sky.drawMs.toFixed(1)}); }, 1000);
  NF.setLens(S.lens);
};
})();
