/* new-UI-face — D4's rules, no DOM: the command bar's results (search + commands), conversations (drafts, context,
   a turn that runs on an injected clock), and the notice history. selftest.html drives all of it with a fake clock.
   Backend today (see README «D4»): search = GET /api/search (items carry their status); a conversation = the
   /api/chat/sessions* routes and their SSE frames; searching conversations, a resource as a chat's context and a
   per-person notice history do not exist yet. */
(function(){
"use strict";
const NF = window.NF = window.NF || {};
const PER_GROUP = 5;

/* what a found thing is called, in the words of its status line */
const stateKey = it => `state.${it.entity}.${NF.stateOf(it)}`;
const isOpen = it => !["fixed", "done", "closed", "cancelled"].includes(it.status);
const everything = store => store.all ? store.all() : store.items;       // what waits and what no longer does

NF.chat = {
  GROUPS: ["issues", "changes", "plans", "resources", "reports", "chats"],

  /* Global search. Groups in a fixed order, at most PER_GROUP rows each; an exact reference comes first, then what is
     still open, then the rest. Things that no longer wait are found too, with their state (a dismissed issue can be
     found again and reopened from its page). `@` = resources only. A command (`/`) is not a search. */
  search(store, nodes, raw, chats){
    const v = (raw || "").trim();
    if (!v || v.startsWith("/")) return [];
    const at = v.startsWith("@"), q = v.replace(/^@/, "").trim().toLowerCase();
    if (!q) return [];
    const ref = q.replace("#", "").toUpperCase(), out = [];
    const push = (g, rows) => { if (rows.length) out.push({g, rows: rows.slice(0, PER_GROUP), more: Math.max(0, rows.length - PER_GROUP)}); };
    if (!at){
      const hit = it => it.id === ref || NF.tx(it.title).toLowerCase().includes(q) || (it.node && it.node.toLowerCase() === q);
      const order = (a, b) => (b.id === ref) - (a.id === ref) || isOpen(b) - isOpen(a) || a.ref.localeCompare(b.ref, "en", {numeric: true});
      const found = everything(store).filter(hit).sort(order);
      const row = it => ({ref: it.ref, title: NF.tx(it.title), state: stateKey(it), open: isOpen(it), go: {item: it.id}});
      push("issues", found.filter(i => i.entity === "issue").map(row));
      push("changes", found.filter(i => i.entity === "change").map(row));
      push("plans", found.filter(i => i.plan).map(it => ({ref: it.ref, title: NF.t("search.planOf", {label: NF.tx(it.plan.label), v: it.plan.version}),
                                                          state: stateKey(it), open: isOpen(it), go: {item: it.id}})));
    }
    const byName = (nodes || []).filter(n => n.name.toLowerCase().includes(q))
      .sort((a, b) => (b.name.toLowerCase() === q) - (a.name.toLowerCase() === q) || b.name.toLowerCase().startsWith(q) - a.name.toLowerCase().startsWith(q) || a.name.localeCompare(b.name));
    push("resources", byName.map(n => ({ref: n.name, title: NF.t("type." + n.type), go: {resource: n.name}, gone: !!n.gone})));
    if (!at){
      push("reports", (NF.seed.reports || []).filter(r => r.title.toLowerCase().includes(q) || r.id.toLowerCase() === q)
        .map(r => ({ref: r.id, title: r.title, go: {report: r.id}})));
      push("chats", (chats || []).filter(c => NF.tx(c.title).toLowerCase().includes(q) || c.turns.some(t => t.q.toLowerCase().includes(q)))
        .map(c => ({ref: c.ctx ? c.ctx.ref : "", title: NF.tx(c.title), go: {chat: c.id}})));
    }
    return out;
  },

  /* The command list (`/`): where to go, what can be done to the thing in front of you, the chat's own commands.
     Only what this person may do is listed: a read-only person gets no decision and no `/send_to`. */
  commands(role, cur){
    const may = role !== "viewer", g = [];
    g.push({g: "go", rows: [
      {id: "lens:decide", k: "cmd.decide", h: "1"}, {id: "lens:live", k: "cmd.live", h: "2"}, {id: "lens:world", k: "cmd.world", h: "3"},
      {id: "lens:chat", k: "cmd.chat", h: "4"}, {id: "history", k: "cmd.history"}, {id: "critical", k: "cmd.critical"}, {id: "all", k: "cmd.all"},
      {id: "theme", k: "cmd.theme", h: "T"}, {id: "keys", k: "cmd.keys", h: "?"},
      {id: "draw:D5", k: "cmd.reports"}, {id: "draw:D5", k: "cmd.schedules"}, {id: "draw:D5", k: "cmd.skills"}, {id: "draw:D6", k: "cmd.settings"}]});
    if (cur){
      const rows = [{id: "ask", k: "cmd.item.ask", h: "E"}, {id: "story", k: "cmd.item.story", h: "↵"}];
      if (may && cur.status === "waiting"){
        if (["approve", "accept", "confirm"].includes(cur.kind)) rows.unshift({id: "primary", k: "cmd.item.primary." + cur.kind, h: "A"});
        rows.push({id: "close", k: cur.entity === "issue" ? "cmd.item.dismiss" : "cmd.item.reject", h: "D"});
      }
      g.push({g: "item", ref: cur.ref, rows});
    }
    if (may) g.push({g: "chat", rows: [{id: "slash:/send_to", k: "cmd.sendTo", h: "/send_to"}, {id: "slash:/channel", k: "cmd.channel", h: "/channel"}]});
    return g;
  },

  /* ── conversations ─────────────────────────────────────────────────────── */
  createChats(seed, clock){
    const list = JSON.parse(JSON.stringify(seed.chats || [])), drafts = {};
    let seq = 0;
    const api = {
      list, clock,
      get: id => list.find(c => c.id === id),
      ordered: () => [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || a.h - b.h),
      draft: id => drafts[id] || "",
      setDraft(id, text){ if (text) drafts[id] = text; else delete drafts[id]; },
      /* A new conversation, maybe about one item: its context is that item's account. The text is left in the
         composer — nothing is sent until the person sends it. */
      open(store, {ref, resource, account, text} = {}){
        const it = ref && everything(store).find(i => i.ref === ref || i.id === ref);
        const ctx = it ? {ref: it.ref, account: it.account} : resource ? {resource, account} : null;
        const c = {id: "n" + (++seq), h: 0, title: it ? NF.t("chat.about", {ref: it.ref}) : resource ? NF.t("chat.about", {ref: resource}) : NF.t("chat.untitled"),
                   ctx, model: "Opus 5.5", effort: "auto", turns: [], fresh: true};
        list.push(c); if (text) drafts[c.id] = text;
        return c;
      },
      /* before the first message the context can still be taken off */
      clearCtx(c){ if (api.ctxLocked(c)) return false; c.ctx = null; c.title = NF.t("chat.untitled"); return true; },
      /* the context can change until the first message is sent; after that it is locked */
      ctxLocked: c => c.turns.length > 0,
      busy: c => c.turns.some(t => t.running),
      /* One turn. The steps arrive one by one (STEP_MS apart), then the answer; a question that asks too much
         ends with a timeout, as a real model stream can. onUpdate after each change. */
      send(store, c, text, files, onUpdate = () => {}, opts = {}){
        text = (text || "").trim();
        if (!text || api.busy(c)) return null;
        const it = c.ctx && c.ctx.ref && everything(store).find(i => i.ref === c.ctx.ref);
        const turn = {q: text, h: 0, running: true, work: [], files: (files || []).map(f => ({...f})), started: 0};
        c.turns.push(turn); c.fresh = false; c.h = 0; delete drafts[c.id];
        if (c.title === NF.t("chat.untitled")) c.title = text.slice(0, 40);
        /* a question about every account runs out of time; its first retry is throttled; the next one answers */
        const slash = /^\/(send_to|channel)\b/.exec(text);
        if (slash){                                       // the chat's own commands: a writer's only (a read-only person runs neither)
          turn.running = false; turn.secs = 0;
          turn.work = [{t: NF.t("chat.work.slash", {cmd: "/" + slash[1]}), c: text, act: true, ms: 200}];
          turn.answer = {text: NF.t(store.canDecide() ? "chat.slash." + slash[1] : "chat.slash.readonly")};
          onUpdate(); return turn;
        }
        const plan = api.cannedWork(text, it), slow = !opts.retry && /所有|全部|every|all accounts/i.test(text), throttled = !!opts.retry && !c.retried;
        if (opts.retry) c.retried = true;
        let k = 0;
        const step = () => {
          if (!turn.running) return;                       // stopped
          if (k < plan.length && !(throttled && k === 1)){ turn.work.push(plan[k++]); onUpdate(); clock.after(NF.STEP_MS, step); return; }
          turn.running = false;
          if (slow || throttled){ turn.error = slow ? "timeout" : "throttled"; onUpdate(); return; }
          turn.secs = Math.round(plan.length * NF.STEP_MS / 1000);
          turn.answer = {text: it ? NF.t("chat.canned.item", {ref: it.ref, cause: NF.tx(it.cause ? it.cause.text : it.title)}) : NF.t("chat.canned.plain")};
          turn.suggest = it ? [NF.t("chat.sugg.open", {ref: it.ref}), NF.t("chat.sugg.why")] : [NF.t("chat.sugg.more")];
          onUpdate();
        };
        clock.after(NF.STEP_MS, step); onUpdate();
        return turn;
      },
      /* «停下»: no further step; what was written stays, marked as stopped */
      stop(c){ const t = c.turns.find(x => x.running); if (!t) return false; t.running = false; t.stopped = true; return true; },
      cannedWork(text, it){
        const steps = [];
        if (it) steps.push({t: NF.t("chat.work.read", {ref: it.ref}), c: `get_health_issue(${it.ref})`, act: true, ms: 800});
        steps.push({t: NF.t("chat.work.fetch"), c: it ? "get_rca_result(" + it.ref + ")" : "list_health_issues()", find: true, ms: 1200});
        steps.push({t: NF.t("chat.work.think"), c: "", ms: 0});
        return steps;
      },
    };
    return api;
  },

  /* ── the notice history ────────────────────────────────────────────────── */
  createHistory(seedNotices){
    const rows = (seedNotices || []).map((n, k) => ({...n, seq: -k}));
    let unseen = 0, seq = 0;
    return {
      /* newest first; a notice stays here after its toast is gone */
      list: () => [...rows].sort((a, b) => a.h - b.h || b.seq - a.seq),
      push(entry){ rows.push({h: 0, ...entry, seq: ++seq}); unseen++; },
      unseen: () => unseen,
      seen(){ unseen = 0; },
    };
  },
};
})();
