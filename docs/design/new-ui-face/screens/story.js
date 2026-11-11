/* new-UI-face — the «经过» page: one item from the moment it was found to its acceptance, as six phases on a spine.
   The brief asks for one decision; this page is the whole record behind it. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, prov = NF.prov;
const PHASES = { issue: ["found", "rca", "plan", "approve", "run", "accept"], change: ["request", "review", "plan", "approve", "run", "accept"] };
/* which phase an item stands in, by its attention situation; `bad` = that phase went wrong */
const AT = { needsReview: "rca", rcaRejected: "rca", toGenerate: "plan", planRejected: "plan", needsNewPlan: "run", awaitingApproval: "approve",
             notQueued: "run", awaitingAcceptance: "accept", passed: "accept", unverified: "accept", draft: "request", needsClarification: "review" };
const AGENT_AT = { open: "rca", investigating: "rca", root_cause_identified: "plan", fix_planned: "plan", fix_executed: "accept", under_review: "review" };
const BAD = { needsNewPlan: true, notQueued: true, planRejected: true, rcaRejected: true };
const who = by => by === "you" ? t("who.you") : (NF.STR.zh["by." + by] ? t("by." + by) : by);
const when = h => h == null ? "" : h >= 48 ? t("ago.d", {n: Math.round(h / 24)}) : NF.clockAt(h) + " UTC";

/* The six phases of an item: {id, state: done | now | bad | closed | todo, time, who, html}. Pure: no DOM. */
NF.storyPhases = it => {
  const ids = PHASES[it.entity], issue = it.entity === "issue", at = it.at || {};
  let cur = AT[it.situation], bad = it.status === "waiting" && !!BAD[it.situation], allDone = false;
  if (it.entity === "change" && cur === "rca") cur = "review";
  if (it.status === "pending" || it.status === "running") cur = "run";
  if (it.status === "fixed" || it.status === "done") allDone = true;
  const working = ["sent", "agent", "handed"].includes(it.status), closed = it.status === "closed";
  if (working && AGENT_AT[it.agentState]) cur = AGENT_AT[it.agentState];      // the step the agent is working on, not the one the decision was made at
  const ci = ids.indexOf(cur);
  const P = (strings, ...v) => `<p>${strings.reduce((a, s, i) => a + s + (v[i] ?? ""), "")}</p>`;
  const body = {
    found: () => P`${prov(true)}${esc(tx(it.found.t))}`,
    request: () => P`${esc(tx(it.found.t))}` + (it.request ? P`${esc(tx(it.request.text))}` : "") + (it.situation === "draft" && it.status === "waiting" ? P`${t("story.request.draft")}` : ""),
    rca: () => !it.cause ? "" : P`${prov(false)}${esc(tx(it.cause.text))}`
      + P`${esc(t("story.rca.summary", {self: NF.briefParts.pct(it.cause.self), critic: t("critic." + it.cause.critic), location: t("location." + it.cause.location)}))}`
      + (it.situation === "needsReview" && it.status === "waiting" ? P`${t("story.rca.needsYou")}` : "")
      + (it.verdict && it.verdict.v === "no" ? P`${t("story.rca.rejected")}` + NF.briefParts.quote(it.verdict.text, when(it.verdict.h)) : "")
      + (it.verdict && it.verdict.v === "yes" ? P`${esc(t("story.rca.confirmed", {by: who(it.verdict.by)}))}` : ""),
    review: () => it.kind === "clarify" && it.status === "waiting" ? P`${prov(false)}${esc(tx(it.stuck))}` + P`${esc(t("story.review.stuck", {n: it.questions.length}))}`
      : it.cause ? P`${prov(false)}${esc(tx(it.cause.text))}` : (ci > 1 || allDone ? P`${t("story.review.passed")}` : ""),
    plan: () => {
      const p = it.plan, r = it.lastRun;
      let h = p ? P`${esc(t("story.plan.summary", {label: tx(p.label), v: p.version, hash: p.hash, n: p.steps.length, w: p.steps.filter(s => s.tier === "write").length}))}`
          + `<details class="more"><summary>${t("story.plan.steps")}</summary>${NF.briefParts.steps(p)}<p class="note">${prov(true)}${esc(t("plan.note", {rollback: tx(p.rollback)}))}</p></details>`
        : r ? P`${esc(tx(r.plan))}　<span class="num">${r.hash}</span>` : it.ran ? P`${esc(tx(it.ran.plan))}${it.ran.hash ? `　<span class="num">${it.ran.hash}</span>` : ""}` : "";
      if (it.situation === "planRejected" && it.status === "waiting") h += P`${esc(t("story.plan.rejected", {v: p.version, by: who(it.rejection.by)}))}` + NF.briefParts.quote(it.rejection.text, when(it.rejection.h));
      if (it.diff) h += P`${esc(t("story.plan.redone", {from: it.diffFrom, to: p.version}))}`;
      if (!h && cur === "plan") h = P`${t("story.plan.none")}`;
      return h;
    },
    approve: () => it.status === "pending" ? P`${t("story.approve.pending")}`
      : cur === "approve" && it.status === "waiting" ? P`${t("story.approve.waiting")}`
      : P`${esc(t("story.approve.done", {by: who(it.approved ? it.approved.by : "you"), t: at.approve != null ? NF.clockAt(at.approve) : NF.clockAt(0)}))}`,
    run: () => {
      if (it.run && !it.run.done) return P`${it.run.pending ? t("feed.pending") + "。" + t("feed.canUndo") + "。" : esc(t("story.run.running", {i: Math.min(it.run.step + 1, it.run.total), n: it.run.total}))}`;
      if (it.status === "fixed") return P`${prov(true)}${t("story.run.fixed")}`;
      if (it.lastRun) return `<details class="more"><summary>${prov(true)}${esc(t("ran.failed", {run: it.lastRun.id, n: it.lastRun.failedAt, duration: tx(it.lastRun.duration)}))}</summary>${NF.briefParts.runSteps(it.lastRun)}</details>`
        + P`${prov(true)}${esc(tx(it.lastRun.rollback))}`;
      if (it.kind === "not_started") return P`${prov(true)}${t("story.run.notStarted")}` + P`${prov(true)}${esc(tx(it.why))}`;
      if (it.ran) return P`${prov(true)}${esc(t("story.run.done", {run: it.ran.run, steps: it.ran.steps}))}`;
      return "";
    },
    accept: () => it.status === "done" || it.status === "fixed" ? P`${t(it.status === "fixed" ? "story.run.fixed" : "story.accept.done")}`
      : it.kind === "accept" ? P`${esc(t("story.accept.waiting", {n: it.needChecks.length}))}`
      : it.situation === "passed" ? P`${t("story.accept.resolve")}` : it.situation === "unverified" ? P`${t("story.accept.noVerdict")}` : "",
  };
  const actor = { found: () => who(it.found.by), request: () => who(it.requester || it.found.by), rca: () => t("by.rca"), review: () => t("by.sre"), plan: () => t("by.sre"),
                  approve: () => "", run: () => t("by.executor"), accept: () => "" };
  const time = { found: it.found.h, request: it.found.h, rca: at.rca, review: at.rca, plan: at.plan, approve: at.approve, run: at.run, accept: null };
  return ids.map((id, i) => {
    const state = allDone ? "done" : i < ci ? "done" : i > ci ? "todo" : closed ? "closed" : bad ? "bad" : "now";
    let html = state === "todo" ? "" : body[id]();
    if (state === "now" && working) html += P`${esc(it.agent ? t("story.agentNow", {task: t(it.agent.taskKey)}) : t("story.handed"))}`;
    if (state === "closed") html = P`${prov(true)}${t(it.entity === "change" ? "story.rejectedChange" : "story.closed")}` + NF.briefParts.quote(it.myReason, t("who.you") + "　" + NF.clockAt(0) + " UTC");
    return { id, state, time: state === "todo" ? null : time[id], who: state === "todo" ? "" : actor[id](), html };
  });
};

function render(){
  const it = NF.store.get(S.story); if (!it){ NF.setLens("decide"); return; }
  if (S.view !== "ready"){                       // loading / failed / not there: the same three pictures as every screen
    const back = `<button class="back" data-do="storyBack">← ${t("story.back")}<kbd>Esc</kbd></button>`;
    $("#storyMain").dataset.id = ""; $("#storyFacts").hidden = true;
    $("#storyMain").innerHTML = back + (S.view === "empty" ? `<div class="state"><div class="big">${t("story.none.big")}</div><p>${t("story.none.p")}</p></div>` : NF.stateBlock(S.view));
    return;
  }
  $("#storyFacts").hidden = false;
  const state = NF.stateOf(it), waits = NF.waitsOn(it), acct = NF.seed.accounts.find(a => a.id === it.account), b = NF.briefs[it.kind];
  const main = $("#storyMain"), keep = main.dataset.id === it.id ? main.scrollTop : 0; main.dataset.id = it.id; main.setAttribute("aria-label", t("story.label"));
  main.innerHTML = `<button class="back" data-do="storyBack">← ${t("story.back")}<kbd>Esc</kbd></button>
    <div class="meta" style="margin-top:10px"><span class="ref">${it.ref}</span><span class="sev ${it.tone}">${NF.sevLabel(it)}</span></div>
    <h1>${esc(tx(it.title))}</h1>
    <div class="statusline"><b>${t(`state.${it.entity}.${state}`)}</b><span class="${waits === "you" ? "wait" : ""}">${t("wait." + waits)}${it.status === "waiting" && !it.snoozed ? "　" + NF.fmtWait(it.waitMin) : ""}</span>
      <span>${acct ? esc(tx(acct.name)) : ""}　${it.region}</span></div>
    ${it.status === "waiting" ? `<p class="ask"><b>${t("ask.lead")}</b>${esc(b.ask(it))}${NF.store.canDecide() ? `　<button class="btn sm" data-do="storyDecide" style="vertical-align:middle"><span class="t">${t("story.goDecide")}</span><kbd>↵</kbd></button>` : ""}</p>` : ""}
    ${it.status === "closed" && it.entity === "issue" && NF.store.canDecide() && !(NF.store.pending() && NF.store.pending().id === it.id)
      ? `<p style="margin:10px 0 0"><button class="btn sm" data-do="storyReopen"><span class="t">${t("act.reopen")}</span></button></p>` : ""}
    <ol class="spine">${NF.storyPhases(it).map(p => `<li class="${p.state}"><h3>${t("phase." + p.id)}${p.time != null ? `<time>${when(p.time)}</time>` : ""}${p.who ? `<span class="who">${esc(p.who)}</span>` : ""}</h3>${p.html}</li>`).join("")}</ol>`;
  main.scrollTop = keep;
  const notes = it.notes || [];
  $("#storyFacts").innerHTML = `<h2>${t("story.facts")}</h2><dl>
      <dt>${t("fact.state")}</dt><dd class="mono">${state}</dd>
      <dt>${t("fact.account")}</dt><dd>${acct ? esc(tx(acct.name)) : "—"}</dd><dt>${t("fact.region")}</dt><dd>${it.region}</dd>
      ${it.node ? `<dt>${t("fact.resource")}</dt><dd>${esc(it.node)}</dd>` : ""}
      ${it.severity ? `<dt>${t("fact.severity")}</dt><dd>${t("sev." + it.severity)}</dd>` : `<dt>${t("fact.risk")}</dt><dd>${it.risk}</dd>`}
      ${it.requester ? `<dt>${t("fact.requester")}</dt><dd>${esc(who(it.requester))}</dd>` : ""}
      <dt>${t("fact.found")}</dt><dd>${when(it.found.h)}</dd>
      ${it.entity === "issue" ? `<dt>${t("fact.signals")}</dt><dd class="num">× ${it.signals}</dd>` : ""}</dl>
    <h2>${t("story.notes")}</h2>
    ${notes.length ? `<ul class="notes">${notes.map(n => `<li>${esc(n.text)}<small>${esc(n.by)}　${NF.clockAt(0)} UTC</small></li>`).join("")}</ul>` : `<p style="margin:0;color:var(--faint)">${t("note.none")}</p>`}
    ${NF.store.canDecide() ? `<form data-form="note" style="display:flex;gap:6px;margin-top:8px"><input class="field" placeholder="${t("note.ph")}" aria-label="${t("note.label")}" maxlength="400" style="min-height:36px;padding:4px 10px">
      <button class="btn sm" type="submit"><span class="t">${t("note.add")}</span></button></form>` : ""}
    <p class="note">${t("note.rule")}</p>`;
}
NF.openStory = id => { if (!NF.store.get(id)) return; S.story = id; NF.setLens("story"); };
Object.assign(NF.on, {
  storyBack: () => { const it = NF.store.get(S.story); if (it && it.status === "waiting") S.cur = it.id; NF.setLens("decide"); },
  storyDecide: () => NF.on.storyBack(),
  storyReopen: () => NF.actions.reopen(NF.store, S.story),
});
NF.onSubmit.note = form => {
  const it = NF.store.get(S.story), i = form.querySelector("input"), v = i.value.trim(); if (!it || !v || !NF.store.canDecide()) return;
  (it.notes = it.notes || []).push({by: NF.seed.user.name, text: v}); render();
};
NF.screens.story = { render, refresh: render, key(e, k){ if (k === "enter"){ e.preventDefault(); NF.on.storyBack(); } } };
})();
